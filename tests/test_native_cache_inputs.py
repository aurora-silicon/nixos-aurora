import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('native_cache_inputs',
    Path(__file__).resolve().parents[1] / 'scripts/collect-cache-inputs.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NativeCacheInputsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.metadata = {
            'head_sha': 'a' * 40, 'head_branch': 'main', 'conclusion': 'success',
            'head_repository': {'full_name': module.REPOSITORY}, 'event': 'push',
            'path': '.github/workflows/checks.yml',
        }

    def test_native_build_requires_successful_merged_main_and_our_workflow(self):
        module.validate_build(self.metadata, lambda _: True)
        for key, bad in [('head_branch', 'feature'), ('conclusion', 'failure'),
                         ('event', 'pull_request'), ('path', '.github/workflows/other.yml'),
                         ('head_sha', 'short'), ('head_repository', {'full_name': 'other/fork'})]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                module.validate_build({**self.metadata, key: bad}, lambda _: True)
        with self.assertRaises(ValueError):
            module.validate_build(self.metadata, lambda _: False)

    def test_derivation_and_every_output_must_match_the_current_flake(self):
        expected = {'drvPath': '/nix/store/current.drv', 'outputs': ['out', 'dev']}
        record = [{'drvPath': expected['drvPath'], 'outputs': {'out': 'out', 'dev': 'dev'}}]
        self.assertTrue(module.current_build(record, expected))
        self.assertFalse(module.current_build(record, {**expected, 'drvPath': 'old.drv'}))
        self.assertFalse(module.current_build(record, {**expected, 'outputs': ['out']}))
        self.assertFalse(module.current_build(record * 2, expected))

    def test_manual_branch_build_requires_merged_source(self):
        manual = {**self.metadata, 'head_branch': 'update/kernel', 'event': 'workflow_dispatch'}
        module.validate_build(manual, lambda _: True)
        with self.assertRaises(ValueError):
            module.validate_build(manual, lambda _: False)
        with self.assertRaises(ValueError):
            module.validate_build({**manual, 'head_repository': {'full_name': 'other/fork'}}, lambda _: True)

    def archive(self, name, mode=0o100600):
        archive = self.root / 'input.zip'
        with zipfile.ZipFile(archive, 'w') as stream:
            entry = zipfile.ZipInfo(name)
            entry.external_attr = mode << 16
            stream.writestr(entry, b'fixture')
        return archive

    def test_zip_rejects_traversal_absolute_paths_symlinks_and_unexpected_files(self):
        for name, mode in [('cache/../../escape', 0o100600), ('/escape', 0o100600),
                           ('cache/link', 0o120777), ('unrelated.txt', 0o100600),
                           ('cache\\escape', 0o100600)]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                module.unpack(self.archive(name, mode), self.root / 'unpacked')
        self.assertFalse((self.root / 'unpacked').exists())

    def test_zip_rejects_duplicate_members_and_insufficient_peak_space(self):
        archive = self.archive('cache/nix-cache-info')
        with patch.object(module.shutil, 'disk_usage') as usage:
            usage.return_value.free = 10 * 1024**3
            with self.assertRaisesRegex(ValueError, 'Insufficient space'):
                module.unpack(archive, self.root / 'unpacked')
        with zipfile.ZipFile(archive, 'a') as stream:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                stream.writestr('cache/nix-cache-info', b'duplicate')
        with self.assertRaisesRegex(ValueError, 'Unsafe cache artifact'):
            module.unpack(archive, self.root / 'unpacked')

    def test_cache_transport_collision_is_never_silently_overwritten(self):
        a, b = self.root / 'input.nar.zst', self.root / 'output.nar.zst'
        a.write_bytes(b'one')
        module.merge_file(a, b)
        module.merge_file(a, b)
        a.write_bytes(b'two')
        with self.assertRaisesRegex(ValueError, 'Conflicting cache transport'):
            module.merge_file(a, b)
        self.assertEqual(b.read_bytes(), b'one')

    def test_only_verified_signature_sets_can_differ_between_duplicate_metadata(self):
        a, b = self.root / 'input.narinfo', self.root / 'output.narinfo'
        a.write_text('StorePath: /nix/store/current\nNarHash: hash\nSig: signer:first\n')
        module.merge_file(a, b)
        a.write_text(a.read_text().replace('signer:first', 'signer:second'))
        module.merge_file(a, b)
        a.write_text(a.read_text().replace('NarHash: hash', 'NarHash: other'))
        with self.assertRaisesRegex(ValueError, 'Conflicting cache identity'):
            module.merge_file(a, b)

    def test_previous_metadata_cannot_claim_another_store_path_or_ambiguous_identity(self):
        p = self.root / ('a' * 32 + '.narinfo')
        p.write_text('StorePath: /nix/store/' + 'a' * 32 + '-fixture\n')
        self.assertEqual(module.store_paths(self.root), {'/nix/store/' + 'a' * 32 + '-fixture'})
        p.write_text(p.read_text().replace('a' * 32, 'b' * 32))
        with self.assertRaisesRegex(ValueError, 'does not match'):
            module.store_paths(self.root)
        p.write_text(('StorePath: /nix/store/' + 'a' * 32 + '-fixture\n') * 2)
        with self.assertRaises(ValueError):
            module.store_paths(self.root)


if __name__ == '__main__':
    unittest.main()
