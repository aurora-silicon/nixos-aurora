import importlib.util
import json
import shutil
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gl_payload', ROOT / 'flatpak-gl/validate-repository.py')
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
COMMIT = 'cf4e08105dfa526b8874318b6a52b3ce948f6297'


class PayloadValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write('.aurora-mesa-commit', COMMIT)
        elf = b'\x7fELF\x02\x01' + bytes(12) + struct.pack('<H', 183)
        for name in ('libvulkan_asahi.so', 'libvulkan_lvp.so', 'libEGL_mesa.so.0',
                     'libGLX_mesa.so.0', 'libLLVM.so.22.1'):
            self.write('lib/' + name, elf + f' Mesa (git-{COMMIT[:10]}), Borealis'.encode())
        for name in ('asahi', 'zink', 'swrast'):
            self.write('lib/dri/' + name + '_dri.so', elf)
        for path, lib in (('vulkan/icd.d/asahi_icd.aarch64.json', 'libvulkan_asahi.so'),
                          ('vulkan/icd.d/lvp_icd.aarch64.json', 'libvulkan_lvp.so'),
                          ('glvnd/egl_vendor.d/50_mesa.json', 'libEGL_mesa.so.0')):
            self.write(path, json.dumps({'ICD': {'library_path': '/usr/lib/aarch64-linux-gnu/GL/aurora/lib/' + lib}}))
        self.write('share/drirc.d/00-hk-defaults.conf', 'hk_report_honeykrisp_driver_id')

    def write(self, path, value):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode() if isinstance(value, str) else value)

    def test_complete_payload(self):
        validator.validate_payload(self.root, COMMIT)

    def test_missing_gl_library_is_rejected_despite_valid_stamp(self):
        (self.root / 'lib/libEGL_mesa.so.0').unlink()
        with self.assertRaises(FileNotFoundError):
            validator.validate_payload(self.root, COMMIT)

    def test_wrong_architecture_is_rejected(self):
        self.write('lib/dri/asahi_dri.so', b'\x7fELF\x02\x01' + bytes(12) + struct.pack('<H', 62))
        with self.assertRaisesRegex(ValueError, 'not an AArch64'):
            validator.validate_payload(self.root, COMMIT)

    def test_unstamped_driver_info_is_rejected(self):
        path = self.root / 'lib/libvulkan_asahi.so'
        path.write_bytes(path.read_bytes()[:20] + b'Mesa 26.3.0-devel, Borealis')
        with self.assertRaisesRegex(ValueError, 'driverInfo'):
            validator.validate_payload(self.root, COMMIT)

    def test_symlink_outside_payload_is_rejected(self):
        path = self.root / 'lib/dri/asahi_dri.so'
        path.unlink()
        path.symlink_to('/bin/sh')
        with self.assertRaisesRegex(ValueError, 'escapes'):
            validator.validate_payload(self.root, COMMIT)

    def test_absent_json_target_is_rejected(self):
        self.write('glvnd/egl_vendor.d/50_mesa.json', json.dumps({'ICD': {'library_path': 'missing.so'}}))
        with self.assertRaisesRegex(ValueError, 'library_path'):
            validator.validate_payload(self.root, COMMIT)


class RepositoryValidationTests(PayloadValidationTests):
    def setUp(self):
        super().setUp()
        self.repo = self.root.parent / (self.root.name + '-repo')
        self.repo.mkdir()
        self.addCleanup(shutil.rmtree, self.repo)
        for branch in validator.BRANCHES:
            tree = self.repo / branch
            shutil.copytree(self.root, tree / 'files')
            (tree / 'metadata').write_text(
                f'[Runtime]\nname={validator.ID}\n'
                f'[ExtensionOf]\nref=runtime/org.freedesktop.Platform/aarch64/{branch}\npriority=10\n')
            (self.repo / f'aurora-mesa-commit.{branch}').write_text(COMMIT)

    def validate_repo(self):
        def checkout(ref, tree):
            shutil.copytree(self.repo / ref.rsplit('/', 1)[1], tree)
        validator.validate(self.repo, COMMIT, checkout)

    def test_both_complete_branches(self):
        self.validate_repo()

    def test_missing_library_in_second_branch(self):
        (self.repo / '26.08/files/lib/libEGL_mesa.so.0').unlink()
        with self.assertRaises(FileNotFoundError):
            self.validate_repo()

    def test_stale_payload_with_correct_outer_stamp(self):
        (self.repo / '26.08/files/.aurora-mesa-commit').write_text('b' * 40)
        with self.assertRaisesRegex(ValueError, 'wrong Mesa commit'):
            self.validate_repo()

    def test_wrong_runtime_and_priority(self):
        path = self.repo / '25.08/metadata'
        text = path.read_text()
        for bad in (text.replace('priority=10', 'priority=0'), text.replace('/25.08', '/24.08')):
            path.write_text(bad)
            with self.assertRaisesRegex(ValueError, 'identity or priority'):
                self.validate_repo()

    def test_stamp_only_export(self):
        shutil.rmtree(self.repo / '25.08/files')
        with self.assertRaises(FileNotFoundError):
            self.validate_repo()
