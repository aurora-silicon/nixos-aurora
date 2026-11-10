import importlib.util
import json
from pathlib import Path
from contextlib import contextmanager
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('build_cache',
    Path(__file__).resolve().parents[1] / 'scripts/import-build-cache.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BuildImportTests(unittest.TestCase):
    def setUp(self):
        self.commit = '1' * 40
        self.run = {'head_sha': self.commit, 'conclusion': 'success',
                    'head_repository': {'full_name': module.REPOSITORY},
                    'path': '.github/workflows/checks.yml', 'event': 'workflow_dispatch'}

    def test_image_import_accepts_only_the_explicit_commit(self):
        module.validate_run(self.run, self.commit)
        with self.assertRaises(ValueError):
            module.validate_run(self.run, '2' * 40)
        with self.assertRaises(ValueError):
            module.validate_run(self.run, 'short')

    def test_failed_foreign_or_unrelated_workflow_is_rejected(self):
        for key, bad in (('conclusion', 'failure'), ('path', '.github/workflows/images.yml'),
                         ('event', 'workflow_run'), ('event', 'pull_request'),
                         ('head_repository', {'full_name': 'other/fork'})):
            with self.subTest(key=key), self.assertRaises(ValueError):
                module.validate_run({**self.run, key: bad}, self.commit)

    def test_only_proven_history_can_supply_an_unchanged_derivation(self):
        older = {**self.run, 'head_sha': '2' * 40}
        module.validate_run(older, self.commit, lambda source: source == '2' * 40)
        with self.assertRaises(ValueError):
            module.validate_run(older, self.commit, lambda _source: False)

    def test_a_stale_or_expired_newer_artifact_does_not_hide_a_current_older_one(self):
        path = '/nix/store/' + 'a' * 32 + '-guest'
        expected = {'fex-mesa': {'drvPath': '/nix/store/current.drv', 'outputs': [path]}}
        runs = [{**self.run, 'id': run_id} for run_id in (3, 2, 1)]
        artifacts = {
            run_id: {'id': run_id, 'name': 'nix-fex-mesa-closure', 'expired': run_id == 3,
                     'size_in_bytes': 100, 'digest': 'sha256:fixture'}
            for run_id in (3, 2, 1)
        }
        attempted = []

        def api(route):
            if '/workflows/checks.yml/runs?' in route:
                return {'workflow_runs': runs}
            run_id = int(route.split('/runs/')[1].split('/')[0])
            return {'total_count': 1, 'artifacts': [artifacts[run_id]]}

        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)

            @contextmanager
            def authenticated(artifact, commit):
                self.assertEqual(commit, self.commit)
                attempted.append(artifact['id'])
                yield artifact['id']

            def verified(source, wanted):
                self.assertEqual(wanted, expected['fex-mesa'])
                return None if source == 2 else ([], cache, {path})

            with patch.object(module.cache_inputs, 'expected_outputs', return_value=expected), \
                 patch.object(module.cache_inputs, 'gh_json', side_effect=api), \
                 patch.object(module.cache_inputs, 'authenticated_artifact', side_effect=authenticated), \
                 patch.object(module.cache_inputs, 'verified_cache', side_effect=verified), \
                 patch.object(module.subprocess, 'run', side_effect=lambda args, **_: SimpleNamespace(
                     returncode=1 if args[:3] == ['nix', 'copy', '--from'] else 0)) as run, \
                 patch.object(module.subprocess, 'check_output', return_value=json.dumps({
                     path: {'narHash': 'sha256-' + 'A' * 43 + '='}})):
                proof = module.import_build(self.commit, ['fex-mesa'])
            self.assertEqual(attempted, [2, 1])
            self.assertEqual(proof['inputs'][0]['artifact'], 1)
            self.assertEqual(proof['narHashes'], {path: 'sha256-' + 'A' * 43 + '='})
            self.assertTrue(any(call.args[0][:3] == ['nix', 'copy', '--no-check-sigs']
                                for call in run.call_args_list))


if __name__ == '__main__':
    unittest.main()
