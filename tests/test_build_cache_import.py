import importlib.util
from pathlib import Path
import unittest

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


if __name__ == '__main__':
    unittest.main()
