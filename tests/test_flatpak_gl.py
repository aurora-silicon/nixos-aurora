import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

manager = load('gl_manager', ROOT / 'flatpak-gl/manage.py')
repository = manager.repository
COMMIT = '1' * 40


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.files = {}
        for branch in repository.BRANCHES:
            (self.root / f'aurora-mesa-commit.{branch}').write_text(COMMIT + '\n')
            ref = f'runtime/{repository.ID}/aarch64/{branch}'
            self.files[ref, '/files/.aurora-mesa-commit'] = COMMIT + '\n'
            self.files[ref, '/metadata'] = (
                f'[Runtime]\nname={repository.ID}\n'
                f'[ExtensionOf]\nref=runtime/org.freedesktop.Platform/aarch64/{branch}\npriority=10\n')
            for file in ('vulkan/icd.d/asahi_icd.aarch64.json', 'vulkan/icd.d/lvp_icd.aarch64.json',
                         'glvnd/egl_vendor.d/50_mesa.json'):
                self.files[ref, '/files/' + file] = '{"library_path":"library"}'

    def validate(self):
        repository.validate(self.root, COMMIT, lambda ref, path: self.files[ref, path])

    def test_both_runtime_branches_are_accepted(self):
        self.validate()

    def test_stale_repository_is_rejected(self):
        (self.root / 'aurora-mesa-commit.26.08').write_text('2' * 40)
        with self.assertRaisesRegex(ValueError, 'stale repository'):
            self.validate()

    def test_correct_outer_stamp_cannot_disguise_stale_payload(self):
        key = (f'runtime/{repository.ID}/aarch64/25.08', '/files/.aurora-mesa-commit')
        self.files[key] = '2' * 40
        with self.assertRaisesRegex(ValueError, 'stale Mesa payload'):
            self.validate()

    def test_missing_branch_and_missing_driver_manifest_fail_closed(self):
        (self.root / 'aurora-mesa-commit.26.08').unlink()
        with self.assertRaises(FileNotFoundError):
            self.validate()
        (self.root / 'aurora-mesa-commit.26.08').write_text(COMMIT)
        del self.files[f'runtime/{repository.ID}/aarch64/25.08', '/files/vulkan/icd.d/asahi_icd.aarch64.json']
        with self.assertRaises(KeyError):
            self.validate()

    def test_incorrect_priority_and_runtime_identity_are_rejected(self):
        key = (f'runtime/{repository.ID}/aarch64/25.08', '/metadata')
        correct = self.files[key]
        for bad in (correct.replace('priority=10', 'priority=0'),
                    correct.replace('/aarch64/25.08', '/aarch64/24.08')):
            with self.subTest(metadata=bad):
                self.files[key] = bad
                with self.assertRaisesRegex(ValueError, 'identity or priority'):
                    self.validate()

    def test_validation_precedes_every_host_mutation(self):
        with patch.object(manager.repository, 'validate', side_effect=ValueError('stale')):
            with patch.object(manager, 'flatpak') as flatpak:
                with self.assertRaises(ValueError):
                    manager.enable(self.root, COMMIT)
                flatpak.assert_not_called()

    def test_both_branches_are_installed_and_pinned_before_overrides(self):
        calls = []
        def flatpak(*args):
            calls.append(args)
            return ''
        with patch.object(manager.repository, 'validate'), patch.object(manager, 'flatpak', side_effect=flatpak):
            manager.enable(self.root, COMMIT)
        self.assertEqual([args[-1] for args in calls if args[0] == 'pin'],
                         [f'runtime/{repository.ID}/aarch64/{branch}' for branch in repository.BRANCHES])
        self.assertEqual(calls[-1][0], 'override')
        self.assertTrue(all('--no-deps' in args and '--no-related' in args
                            for args in calls if args[0] == 'install'))


class CleanupTests(unittest.TestCase):
    def test_an_administrators_replacement_remote_keeps_its_runtimes(self):
        calls = []
        def flatpak(*args):
            calls.append(args)
            return 'aurora-gl\thttps://admin.example/repo\n'
        with patch.object(manager, 'remove_owned_overrides'), patch.object(manager, 'flatpak', side_effect=flatpak):
            manager.disable('/nix/store/our-repository')
        self.assertEqual(calls, [('remotes', '--columns=name,url')])

    def test_an_administrators_managed_override_symlink_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'managed'
            target.write_text('[Environment]\n' + '\n'.join(f'{key}={value}' for key, value in manager.ENV.items()) + '\n')
            path = Path(directory) / 'global'
            path.symlink_to(target)
            manager.remove_owned_overrides(path)
            self.assertTrue(path.is_symlink())
            self.assertIn('VK_DRIVER_FILES=', target.read_text())

    def test_removing_owned_keys_preserves_admin_values_and_other_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'global'
            path.write_text('[Context]\nshared=network;\n[Environment]\n'
                            + '\n'.join(f'{key}={value}' for key, value in manager.ENV.items()
                                        if key != 'VK_DRIVER_FILES')
                            + '\nVK_DRIVER_FILES=/admin/driver.json\nOTHER=value\n')
            manager.remove_owned_overrides(path)
            self.assertEqual(path.read_text(), '[Context]\nshared=network;\n[Environment]\n'
                             'VK_DRIVER_FILES=/admin/driver.json\nOTHER=value\n')
            manager.remove_owned_overrides(path)
            self.assertTrue(path.exists())

    def test_an_empty_override_is_removed_and_cleanup_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'global'
            path.write_text('[Environment]\n' + '\n'.join(f'{key}={value}' for key, value in manager.ENV.items()) + '\n')
            manager.remove_owned_overrides(path)
            self.assertFalse(path.exists())
            manager.remove_owned_overrides(path)


if __name__ == '__main__':
    unittest.main()
