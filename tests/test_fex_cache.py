import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('fex_cache',
    Path(__file__).resolve().parents[1] / 'scripts/import-fex-cache.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FexImportTests(unittest.TestCase):
    def setUp(self):
        self.commit = '1' * 40
        self.run = {'head_sha': self.commit, 'conclusion': 'success',
                    'head_repository': {'full_name': module.REPOSITORY},
                    'path': '.github/workflows/checks.yml', 'event': 'pull_request'}

    def test_image_import_accepts_only_the_explicit_commit(self):
        module.validate_run(self.run, self.commit)
        with self.assertRaises(ValueError):
            module.validate_run(self.run, '2' * 40)
        with self.assertRaises(ValueError):
            module.validate_run(self.run, 'short')

    def test_failed_foreign_or_unrelated_workflow_is_rejected(self):
        for key, bad in (('conclusion', 'failure'), ('path', '.github/workflows/images.yml'),
                         ('event', 'workflow_run'), ('head_repository', {'full_name': 'other/fork'})):
            with self.subTest(key=key), self.assertRaises(ValueError):
                module.validate_run({**self.run, key: bad}, self.commit)


if __name__ == '__main__':
    unittest.main()
