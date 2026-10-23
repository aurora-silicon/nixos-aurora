"""Host tests for the installed-system Stage 2 refresh and the channel flake.

install-stage2.sh runs for real against a temporary directory standing in for
the ESP; only the mount and partition queries are replaced by stubs, so every
file operation (staging, verification, backup, rename) is the production
code path.
"""
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / 'scripts/install-stage2.sh'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_stage2 = load('check_stage2', ROOT / 'scripts/check-stage2.py')
follow_channel = load('follow_channel', ROOT / 'scripts/follow-channel.py')


def device_tree(compatible):
    """A minimal valid flattened device tree whose root has `compatible`."""
    strings = b'compatible\0'
    value = compatible.encode() + b'\0'
    padded = value + b'\0' * (-len(value) % 4)
    body = (struct.pack('>I', 1) + b'\0\0\0\0'
            + struct.pack('>III', 3, len(value), 0) + padded
            + struct.pack('>I', 2) + struct.pack('>I', 9))
    header_size = 40
    struct_offset = header_size
    strings_offset = struct_offset + len(body)
    total = strings_offset + len(strings)
    header = struct.pack('>10I', 0xD00DFEED, total, struct_offset, strings_offset, header_size,
                         17, 16, 0, len(strings), len(body))
    return header + body + strings


def stage2(boards=('j274', 'j700'), options=b'', aura=b'AURA-STAGE2-BINARY'):
    return aura + b''.join(device_tree(f'apple,{board}') for board in boards) + gzip.compress(b'u-boot') + options


class CheckStage2Tests(unittest.TestCase):
    def test_combined_layout_is_accepted_and_described(self):
        manifest = check_stage2.check(stage2(options=b'chosen.bootargs=quiet\n'), b'AURA-STAGE2-BINARY', ['j700'])
        self.assertEqual(manifest['boards'], ['apple,j274', 'apple,j700'])
        self.assertEqual(manifest['options'], ['chosen.bootargs=quiet'])

    def test_deviations_are_refused(self):
        aura = b'AURA-STAGE2-BINARY'
        bad = {
            'other aura': (stage2(aura=b'OTHER-AURA-BINARY!'), ['j700']),
            'no device trees': (aura + gzip.compress(b'u-boot'), []),
            'no MacBook Neo': (stage2(boards=('j274',)), ['j700']),
            'U-Boot not gzip': (aura + device_tree('apple,j700') + b'raw u-boot', []),
            'trailing garbage': (stage2(options=b'\x00\x01binary'), []),
        }
        for name, (image, required) in bad.items():
            with self.subTest(name), self.assertRaises(ValueError):
                check_stage2.check(image, aura, required)


@unittest.skipUnless(shutil.which('bash') and shutil.which('sha256sum'), 'bash and coreutils are required')
class InstallStage2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.esp = root / 'esp'
        (self.esp / 'm1n1').mkdir(parents=True)
        (self.esp / 'aurora').mkdir()
        self.stage1 = self.esp / 'aurora/stage1.bin'
        self.stage1.write_bytes(b'stage 1 must never change')
        self.target = self.esp / 'm1n1/boot.bin'
        self.target.write_bytes(b'installed stage 2')
        self.source = root / 'stage2'
        self.source.mkdir()
        self.write_source(stage2())
        self.stubs = root / 'bin'
        self.stubs.mkdir()
        self.state = {'mounted': '1', 'fstype': 'vfat', 'partuuid': 'abcd-1234'}
        self.device_tree = root / 'chosen-esp'
        self.device_tree.write_bytes(b'ABCD-1234\0')

    def write_source(self, data):
        (self.source / 'boot.bin').write_bytes(data)
        (self.source / 'boot.bin.sha256').write_text(hashlib.sha256(data).hexdigest() + '\n')

    def stub(self, name, script):
        path = self.stubs / name
        path.write_text('#!/usr/bin/env bash\n' + script)
        path.chmod(0o755)

    def run_install(self):
        state = self.state
        self.stub('mountpoint', f'exit {0 if state["mounted"] == "1" else 1}\n')
        self.stub('findmnt', 'case " $* " in *FSTYPE*) echo ' + state['fstype'] + ';; *SOURCE*) echo /dev/fake1;; esac\n')
        self.stub('lsblk', f'echo {state["partuuid"]}\n')
        env = dict(os.environ, PATH=f'{self.stubs}:{os.environ["PATH"]}',
                   AURORA_DEVICE_TREE_ESP=str(self.device_tree))
        return subprocess.run(['bash', str(INSTALL), str(self.source), str(self.esp)], env=env,
                              capture_output=True, text=True)

    def assert_untouched(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('left unchanged', result.stderr)
        self.assertEqual(self.target.read_bytes(), b'installed stage 2')
        self.assertFalse((self.esp / 'm1n1/boot.bin.old').exists())
        self.assertFalse((self.esp / 'm1n1/boot.bin.new').exists())

    def tearDown(self):
        self.assertEqual(self.stage1.read_bytes(), b'stage 1 must never change')

    def test_changed_stage2_is_installed_and_the_previous_one_kept(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target.read_bytes(), stage2())
        self.assertEqual((self.esp / 'm1n1/boot.bin.old').read_bytes(), b'installed stage 2')
        self.assertFalse((self.esp / 'm1n1/boot.bin.new').exists())

    def test_unchanged_stage2_writes_nothing(self):
        self.target.write_bytes(stage2())
        old = self.esp / 'm1n1/boot.bin.old'
        old.write_bytes(b'older generation')
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(old.read_bytes(), b'older generation')

    def test_first_install_without_a_previous_file(self):
        self.target.unlink()
        self.assertEqual(self.run_install().returncode, 0)
        self.assertEqual(self.target.read_bytes(), stage2())
        self.assertFalse((self.esp / 'm1n1/boot.bin.old').exists())

    def test_missing_or_mismatched_inputs_are_refused(self):
        (self.source / 'boot.bin.sha256').write_text('0' * 64 + '\n')
        self.assert_untouched(self.run_install())
        (self.source / 'boot.bin').unlink()
        self.assert_untouched(self.run_install())

    def test_wrong_or_unmounted_esp_is_refused(self):
        for key, value in [('mounted', '0'), ('fstype', 'ext4'), ('partuuid', 'ffff-0000')]:
            with self.subTest(key):
                saved = dict(self.state)
                self.state[key] = value
                self.assert_untouched(self.run_install())
                self.state = saved

    def test_esp_without_m1n1_directory_is_refused(self):
        self.target.unlink()
        (self.esp / 'm1n1').rmdir()
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.esp / 'm1n1').exists())

    def test_without_the_device_tree_record_the_mounted_esp_is_used(self):
        self.device_tree.unlink()
        self.assertEqual(self.run_install().returncode, 0)


class FollowChannelTests(unittest.TestCase):
    REV = 'a' * 40

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        (self.dir / 'flake.nix').write_text(
            '{\n  inputs.aurora.url = "github:aurora-silicon/nixos-aurora/' + self.REV + '";\n}\n')
        self.lock = {'nodes': {
            'aurora': {'inputs': {'nixpkgs': 'nixpkgs'},
                       'locked': {'lastModified': 1, 'narHash': 'sha256-x', 'owner': 'aurora-silicon',
                                  'repo': 'nixos-aurora', 'rev': self.REV, 'type': 'github'},
                       'original': {'owner': 'aurora-silicon', 'repo': 'nixos-aurora', 'rev': self.REV,
                                    'type': 'github'}},
            'nixpkgs': {'locked': {}, 'original': {}},
            'root': {'inputs': {'aurora': 'aurora'}}}, 'root': 'root', 'version': 7}
        (self.dir / 'flake.lock').write_text(json.dumps(self.lock))

    def test_channel_input_keeps_the_locked_commit(self):
        follow_channel.follow(self.dir, self.REV, 'testing')
        self.assertIn('"github:aurora-silicon/nixos-aurora/channel-testing"', (self.dir / 'flake.nix').read_text())
        lock = json.loads((self.dir / 'flake.lock').read_text())
        self.assertEqual(lock['nodes']['aurora']['locked']['rev'], self.REV)
        self.assertEqual(lock['nodes']['aurora']['original'],
                         {'owner': 'aurora-silicon', 'ref': 'channel-testing', 'repo': 'nixos-aurora', 'type': 'github'})
        self.assertIn('sudo aurora-update', (self.dir / 'README').read_text())

    def test_pinned_keeps_the_exact_commit_input(self):
        follow_channel.follow(self.dir, self.REV, 'pinned')
        self.assertIn(self.REV, (self.dir / 'flake.nix').read_text())
        self.assertEqual(json.loads((self.dir / 'flake.lock').read_text()), self.lock)

    def test_a_lock_for_another_commit_is_refused(self):
        with self.assertRaises(ValueError):
            follow_channel.follow(self.dir, 'b' * 40, 'testing')


if __name__ == '__main__':
    unittest.main()
