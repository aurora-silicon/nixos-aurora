import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cache_channels', ROOT / 'scripts/cache-channels.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CacheReleaseAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.commit = 'a' * 40

    def download(self, *args):
        directory = self.root / 'work/release'
        (directory / 'manifest.json').write_text(json.dumps({'commit': self.commit}))

    def test_release_must_cover_the_exact_target_commit_before_http_verification(self):
        expected = {'kernel': {'outputs': ['/nix/store/' + 'a' * 32 + '-new-kernel']}}
        with patch.object(module.lib, 'gh', side_effect=self.download), \
             patch.object(module.lib, 'gh_api', return_value={'target_commitish': self.commit}), \
             patch.object(module.lib, 'is_ancestor', return_value=True), \
             patch.object(module, 'verify_attestation', return_value='verified'), \
             patch.object(module, 'expected_outputs', return_value=expected) as evaluate, \
             patch.object(module, 'store_paths', return_value=set()), \
             patch.object(module.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'omits current hardware outputs: kernel'):
                module.authenticate_release('aurora-silicon/nixos-aurora', 'cache-test',
                                            self.root / 'site', self.root / 'work')
        evaluate.assert_called_once_with(self.commit)
        self.assertEqual(run.call_count, 1)  # Extraction only; no HTTP admission.

    def test_manifest_cannot_be_relabelled_as_another_release_commit(self):
        with patch.object(module.lib, 'gh', side_effect=self.download), \
             patch.object(module.lib, 'gh_api', return_value={'target_commitish': 'b' * 40}), \
             patch.object(module.lib, 'is_ancestor', return_value=True), \
             patch.object(module, 'verify_attestation', return_value='verified'), \
             patch.object(module.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'manifest does not name the release target'):
                module.authenticate_release('aurora-silicon/nixos-aurora', 'cache-test',
                                            self.root / 'site', self.root / 'work')
        run.assert_not_called()

    def test_attestation_failure_stops_before_extraction(self):
        with patch.object(module.lib, 'gh', side_effect=self.download), \
             patch.object(module, 'verify_attestation', side_effect=RuntimeError('bad provenance')), \
             patch.object(module.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'bad provenance'):
                module.authenticate_release('aurora-silicon/nixos-aurora', 'cache-test',
                                            self.root / 'site', self.root / 'work')
        run.assert_not_called()

    def test_manifest_bytes_must_match_the_attested_checksum_list(self):
        names = ['cache-metadata.tar.gz', 'manifest.json']
        records = []
        for name in names:
            path = self.root / name
            path.write_bytes(name.encode())
            records.append((name, hashlib.sha256(path.read_bytes()).hexdigest()))
        (self.root / 'SHA256SUMS').write_text(''.join(f'{digest}  {name}\n' for name, digest in records))
        result = [{'verificationResult': {'statement': {'subject': [
            {'name': name, 'digest': {'sha256': digest}} for name, digest in records]}}}]
        with patch.object(module.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(result))):
            self.assertEqual(module.verify_attestation(self.root, 'aurora-silicon/nixos-aurora'), 'verified')
        (self.root / 'manifest.json').write_text('tampered')
        with patch.object(module.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'SHA256SUMS does not match manifest.json'):
                module.verify_attestation(self.root, 'aurora-silicon/nixos-aurora')
        run.assert_not_called()


class CacheDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.enterContext(patch.dict(os.environ, {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'}))
        self.git('init', '-q', '-b', 'main')
        (self.repo / 'sources.json').write_text('{}\n')
        self.old = self.commit('old modules')
        (self.repo / 'module.nix').write_text('{ }\n')
        self.new = self.commit('new modules with identical source pins')
        self.target = self.old
        (self.repo / 'keys').mkdir()
        (self.repo / 'keys/cache.pub').write_text('fixture-public-key\n')
        self.enterContext(patch.object(module, 'ROOT', self.repo))
        self.state = module.lib.empty_channels('aurora-silicon/nixos-aurora')
        self.state['cache'] = {'commit': self.new, 'tag': 'cache-new'}
        self.state['channels']['testing'] = {'commit': self.new, 'tag': 'cache-new'}
        self.path = '/nix/store/' + 'a' * 32 + '-old-output'
        self.missing = '/nix/store/' + 'b' * 32 + '-new-output'
        self.args = SimpleNamespace(repository='aurora-silicon/nixos-aurora', tag='cache-old',
                                    site=self.root / 'site', work=self.root / 'work',
                                    state_out=self.root / 'next-state.json',
                                    allow_downgrade=False, advance_testing=True)

    def git(self, *args):
        return subprocess.check_output([
            'git', '-C', str(self.repo), '-c', 'user.name=Deployment fixture',
            '-c', 'user.email=deploy@example.invalid', '-c', 'commit.gpgsign=false', *args,
        ], text=True, stderr=subprocess.PIPE).strip()

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD')

    def authenticate(self, repository, tag, site, work):
        cache = Path(site) / 'cache'
        cache.mkdir(parents=True)
        (cache / ('a' * 32 + '.narinfo')).write_text('StorePath: ' + self.path + '\n')
        (cache / 'nix-cache-info').write_text('StoreDir: /nix/store\n')
        return {'target_commitish': self.target, 'created_at': '2026-01-01T00:00:00Z'}, 'verified'

    def deploy(self, expected):
        with patch.object(module.lib, 'load_channels', return_value=self.state), \
             patch.object(module, 'authenticate_release', side_effect=self.authenticate), \
             patch.object(module, 'expected_outputs', return_value=expected):
            module.assemble(self.args)

    def test_old_same_pin_release_requires_explicit_rollback_at_deployment(self):
        for cached, served in [(self.new, self.old), (self.old, self.new)]:
            with self.subTest(cached=cached, served=served):
                self.state['cache']['commit'] = cached
                self.state['channels']['testing']['commit'] = served
                self.args.site = self.root / ('site-' + cached + served)
                with self.assertRaisesRegex(SystemExit, 'allow-downgrade'):
                    self.deploy({'fixture': {'outputs': [self.path]}})
                self.assertFalse(self.args.state_out.exists())

    def test_approved_rollback_cannot_remove_unchanged_stable_outputs(self):
        self.args.allow_downgrade = True
        self.state['channels']['stable'] = {'commit': self.new, 'tag': 'cache-new'}
        with self.assertRaisesRegex(ValueError, 'stable.*cumulative cache'):
            self.deploy({'fixture': {'outputs': [self.missing]}})
        self.assertFalse(self.args.state_out.exists())

    def test_cache_only_rollback_cannot_remove_unchanged_testing_outputs(self):
        self.args.allow_downgrade = True
        self.args.advance_testing = False
        with self.assertRaisesRegex(ValueError, 'testing.*cumulative cache'):
            self.deploy({'fixture': {'outputs': [self.missing]}})
        self.assertFalse(self.args.state_out.exists())

    def test_approved_rollback_with_retained_channel_coverage_succeeds(self):
        self.args.allow_downgrade = True
        self.state['channels']['stable'] = {'commit': self.new, 'tag': 'cache-new'}
        self.deploy({'fixture': {'outputs': [self.path]}})
        state = json.loads(self.args.state_out.read_text())
        self.assertEqual(state['channels']['testing']['commit'], self.old)
        self.assertEqual(state['channels']['stable']['commit'], self.new)

    def test_forward_deployment_keeps_unchanged_stable_resolvable(self):
        self.target = self.new
        self.state['cache']['commit'] = self.old
        self.state['channels']['testing']['commit'] = self.old
        self.state['channels']['stable'] = {'commit': self.old, 'tag': 'cache-old'}
        self.deploy({'fixture': {'outputs': [self.path]}})
        state = json.loads(self.args.state_out.read_text())
        self.assertEqual(state['channels']['testing']['commit'], self.new)
        self.assertEqual(state['channels']['stable']['commit'], self.old)

    def test_same_pin_stable_rollback_requires_explicit_permission(self):
        self.state['channels']['stable'] = {'commit': self.new, 'tag': 'cache-new'}
        self.state['history'] = [{'channel': 'testing', 'commit': self.old,
                                  'tag': 'cache-old', 'deployed_at': '2026-01-01T00:00:00Z'}]
        args = SimpleNamespace(repository=self.args.repository, commit=self.old, min_soak_hours=0,
                               allow_downgrade=False, cache_url='https://cache.example.invalid',
                               state_out=self.args.state_out)
        check_output = subprocess.check_output
        run = subprocess.run

        def evaluate(command, *positional, **keywords):
            return json.dumps([self.path]) if command[0] == 'nix' else check_output(command, *positional, **keywords)

        def verify(command, *positional, **keywords):
            return subprocess.CompletedProcess(command, 0) if command[0] == 'nix' else run(command, *positional, **keywords)

        with patch.object(module.lib, 'load_channels', return_value=self.state), \
             patch.object(module.subprocess, 'check_output', side_effect=evaluate), \
             patch.object(module.subprocess, 'run', side_effect=verify):
            with self.assertRaisesRegex(SystemExit, 'allow-downgrade'):
                module.promote(args)
            self.assertFalse(args.state_out.exists())
            args.allow_downgrade = True
            module.promote(args)
        state = json.loads(args.state_out.read_text())
        self.assertEqual(state['channels']['stable']['commit'], self.old)


if __name__ == '__main__':
    unittest.main()
