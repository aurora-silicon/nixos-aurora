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
import re
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
prepare_stage2 = load('prepare_stage2', ROOT / 'scripts/prepare-stage2.py')
prepare_ctxr = load('prepare_ctxr_stage2', ROOT / 'scripts/prepare-ctxr-stage2.py')
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
    return aura + b''.join(device_tree(f'apple,{board}') for board in boards) + gzip.compress(b'u-boot', mtime=0) + options


# Every chip AuraStage1Format.usesMachO admits or names, and every one below it.
MACHO_CHIPS = ('t8132', 't6040', 't6041', 't8140', 't8142', 't8152', 't6050', 't6051', 't6052', 't8130', 't8fff', 't6fff')
EARLIER_CHIPS = ('t8103', 't8112', 't8122', 't6000', 't6001', 't6002', 't6020', 't6021', 't6022', 't6030', 't6031', 't6034', 't8015')


def compatible_file(board, chip):
    return f'apple,{board}\0apple,{chip}\0apple,arm-platform\0'.encode()


def full_device_tree(board, chip, padding=0):
    """A device tree whose root names its board, then its chip."""
    strings = b'compatible\0'
    value = f'apple,{board}\0apple,{chip}\0apple,arm-platform\0'.encode()
    padded = value + b'\0' * (-len(value) % 4)
    body = (struct.pack('>I', 1) + b'\0\0\0\0'
            + struct.pack('>III', 3, len(value), 0) + padded
            + struct.pack('>I', 2) + struct.pack('>I', 9))
    strings_offset = 40 + len(body)
    total = strings_offset + len(strings) + padding
    header = struct.pack('>10I', 0xD00DFEED, total, 40, strings_offset, 40, 17, 16, 0, len(strings), len(body))
    return header + body + strings + b'\0' * padding


class CheckStage2Tests(unittest.TestCase):
    def test_combined_layout_is_accepted_and_described(self):
        manifest = check_stage2.check(stage2(options=b'chosen.bootargs=quiet\n'), b'AURA-STAGE2-BINARY', ['j700'])
        self.assertEqual(manifest['boards'], ['apple,j274', 'apple,j700'])
        self.assertEqual(manifest['options'], ['chosen.bootargs=quiet'])

    def test_deviations_are_refused(self):
        aura = b'AURA-STAGE2-BINARY'
        bad = {
            'other aura': (stage2(aura=b'OTHER-AURA-BINARY!'), ['j700']),
            'no device trees': (aura + gzip.compress(b'u-boot', mtime=0), []),
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
        # Both Stage 1 forms belong to the installer.
        self.stage1 = {self.esp / 'aurora' / name: b'stage 1 must never change: ' + name.encode()
                       for name in ('stage1.bin', 'stage1.macho')}
        for path, data in self.stage1.items():
            path.write_bytes(data)
        self.target = self.esp / 'm1n1/boot.bin'
        self.target.write_bytes(b'installed stage 2')
        os.utime(self.target, (1000000, 1000000))
        self.source = root / 'stage2'
        self.source.mkdir()
        self.write_source(stage2())
        self.stubs = root / 'bin'
        self.stubs.mkdir()
        self.state = {'mounted': '1', 'fstype': 'vfat', 'partuuid': 'abcd-1234'}
        self.device_tree = root / 'chosen-esp'
        self.device_tree.write_bytes(b'ABCD-1234\0')
        self.compatible = root / 'compatible'
        self.compatible.write_bytes(compatible_file('j274', 't8103'))
        self.ctxr = self.esp / 'm1n1/boot-ctxr.bin'

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
                   AURORA_DEVICE_TREE_ESP=str(self.device_tree),
                   AURORA_DEVICE_TREE_COMPATIBLE=str(self.compatible))
        return subprocess.run(['bash', str(INSTALL), str(self.source), str(self.esp)], env=env,
                              capture_output=True, text=True)

    def assert_untouched(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('left unchanged', result.stderr)
        self.assertEqual(self.target.read_bytes(), b'installed stage 2')
        self.assertFalse((self.esp / 'm1n1/boot.bin.old').exists())
        self.assertFalse((self.esp / 'm1n1/boot.bin.new').exists())

    def write_ctxr_source(self, board, data):
        (self.source / 'monitor-free').touch()
        directory = self.source / 'ctxr'
        directory.mkdir(exist_ok=True)
        (directory / f'boot-ctxr-{board}.bin').write_bytes(data)
        (directory / f'boot-ctxr-{board}.bin.sha256').write_text(hashlib.sha256(data).hexdigest() + '\n')

    def assert_frozen(self):
        self.assertEqual(self.target.read_bytes(), b'installed stage 2')
        self.assertEqual(self.target.stat().st_mtime, 1000000)
        self.assertFalse((self.esp / 'm1n1/boot.bin.old').exists())
        self.assertFalse((self.esp / 'm1n1/boot.bin.new').exists())

    def tearDown(self):
        for path, data in self.stage1.items():
            self.assertEqual(path.read_bytes(), data)

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

    def test_macho_without_the_marker_keeps_updating_boot_bin(self):
        for chip in MACHO_CHIPS:
            with self.subTest(chip):
                self.target.write_bytes(b'installed stage 2')
                (self.esp / 'm1n1/boot.bin.old').unlink(missing_ok=True)
                self.compatible.write_bytes(compatible_file('j700', chip))
                result = self.run_install()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.target.read_bytes(), stage2())
                self.assertEqual((self.esp / 'm1n1/boot.bin.old').read_bytes(), b'installed stage 2')
                self.assertFalse(self.ctxr.exists())
                self.assertEqual(result.stderr, '')

    def test_macho_with_the_marker_leaves_boot_bin_byte_identical(self):
        self.write_ctxr_source('j700', stage2(boards=('j700',)))
        for chip in MACHO_CHIPS:
            with self.subTest(chip):
                self.compatible.write_bytes(compatible_file('j700', chip))
                self.ctxr.unlink(missing_ok=True)
                result = self.run_install()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_frozen()
                self.assertEqual(self.ctxr.read_bytes(), stage2(boards=('j700',)))

    def test_macho_with_the_marker_says_where_the_update_went_and_warns_nothing(self):
        self.compatible.write_bytes(compatible_file('j700', 't8140'))
        self.write_ctxr_source('j700', stage2(boards=('j700',)))
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertIn('m1n1/boot-ctxr.bin', result.stdout)
        self.assert_frozen()

    def test_macho_update_keeps_the_previous_ctxr_stage2(self):
        self.compatible.write_bytes(compatible_file('j700', 't8140'))
        self.write_ctxr_source('j700', stage2(boards=('j700',)))
        self.assertEqual(self.run_install().returncode, 0)
        self.assertFalse((self.esp / 'm1n1/boot-ctxr.bin.old').exists())
        self.write_ctxr_source('j700', stage2(boards=('j700',), options=b'chosen.bootargs=quiet\n'))
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.esp / 'm1n1/boot-ctxr.bin.old').read_bytes(), stage2(boards=('j700',)))
        self.assertFalse((self.esp / 'm1n1/boot-ctxr.bin.new').exists())
        self.assertIn('m1n1/boot-ctxr.bin.old', result.stdout)
        self.assert_frozen()

    def test_macho_unchanged_stage2_writes_nothing(self):
        self.compatible.write_bytes(compatible_file('j700', 't8140'))
        self.write_ctxr_source('j700', stage2(boards=('j700',)))
        self.ctxr.write_bytes(stage2(boards=('j700',)))
        old = self.esp / 'm1n1/boot-ctxr.bin.old'
        old.write_bytes(b'older generation')
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')
        self.assertEqual(old.read_bytes(), b'older generation')
        self.assert_frozen()

    def test_macho_board_the_build_does_not_carry_warns_and_keeps_the_rebuild_going(self):
        self.compatible.write_bytes(compatible_file('j873g', 't8152'))
        self.write_ctxr_source('j700', stage2(boards=('j700',)))
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('no Stage 2 for j873g', result.stderr)
        self.assert_frozen()
        self.assertFalse(self.ctxr.exists())

    def test_macho_board_file_without_a_digest_warns_and_keeps_the_rebuild_going(self):
        self.compatible.write_bytes(compatible_file('j700', 't8140'))
        self.write_ctxr_source('j700', stage2(boards=('j700',)))
        (self.source / 'ctxr/boot-ctxr-j700.bin.sha256').unlink()
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('no Stage 2 for j700', result.stderr)
        self.assert_frozen()
        self.assertFalse(self.ctxr.exists())

    def test_macho_mismatched_digest_is_refused(self):
        self.compatible.write_bytes(compatible_file('j700', 't8140'))
        self.write_ctxr_source('j700', stage2(boards=('j700',)))
        (self.source / 'ctxr/boot-ctxr-j700.bin.sha256').write_text('0' * 64 + '\n')
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assert_frozen()
        self.assertFalse(self.ctxr.exists())

    def test_earlier_chips_are_the_same_with_and_without_the_marker(self):
        for marked in (False, True):
            if marked:
                self.write_ctxr_source('j274', b'must not be installed')
            for chip in EARLIER_CHIPS:
                with self.subTest(chip=chip, marked=marked):
                    self.target.write_bytes(b'installed stage 2')
                    (self.esp / 'm1n1/boot.bin.old').unlink(missing_ok=True)
                    self.compatible.write_bytes(compatible_file('j274', chip))
                    result = self.run_install()
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(self.target.read_bytes(), stage2())
                    self.assertEqual((self.esp / 'm1n1/boot.bin.old').read_bytes(), b'installed stage 2')
                    self.assertFalse(self.ctxr.exists())
                    self.assertEqual(result.stderr, '')

    def test_without_a_compatible_it_installs_boot_bin(self):
        (self.source / 'monitor-free').touch()
        self.compatible.unlink()
        self.assertEqual(self.run_install().returncode, 0)
        self.assertEqual(self.target.read_bytes(), stage2())
        self.assertFalse(self.ctxr.exists())

    def test_another_machine_installs_boot_bin(self):
        (self.source / 'monitor-free').touch()
        self.compatible.write_bytes(b'linux,dummy-virt\0')
        self.assertEqual(self.run_install().returncode, 0)
        self.assertEqual(self.target.read_bytes(), stage2())
        self.assertFalse(self.ctxr.exists())


class PrepareCtxrStage2Tests(unittest.TestCase):
    AURA = b'AURA-STAGE2-BINARY'
    BOARDS = {'j274': 't8103', 'j700': 't8140', 'j616s': 't6040', 'j614s': 't6040', 'j713': 't8132', 'j873g': 't8152'}

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        trailer = gzip.compress(b'u-boot', mtime=0)
        # The layout the installed system's build reads: every tree of the kernel.
        self.combined = self.root / 'boot.bin'
        self.combined.write_bytes(self.AURA + b''.join(full_device_tree(board, chip) for board, chip in self.BOARDS.items()) + trailer)
        self.aura = self.root / 'aura.bin'
        self.aura.write_bytes(self.AURA)

    def split(self, output):
        output.mkdir(parents=True, exist_ok=True)
        return prepare_stage2.prepare(self.combined, self.aura, output)

    def test_installed_system_build_keeps_only_macho_boards_each_with_its_own_tree(self):
        boards = self.root / 'boards'
        self.split(boards)
        ctxr = self.root / 'ctxr'
        written = prepare_ctxr.prepare(boards, ctxr)
        self.assertEqual(sorted(written), ['boot-ctxr-j614s.bin', 'boot-ctxr-j616s.bin', 'boot-ctxr-j700.bin',
                                           'boot-ctxr-j713.bin', 'boot-ctxr-j873g.bin'])
        image = (ctxr / 'boot-ctxr-j700.bin').read_bytes()
        manifest = check_stage2.check(image, self.AURA, ['j700'])
        self.assertEqual(manifest['boards'], ['apple,j700'])
        self.assertEqual(manifest['deviceTrees'], 1)

    def test_image_esp_carries_both_files_and_each_macho_boards_own(self):
        esp = self.root / 'esp/m1n1'
        self.split(esp)
        (esp / 'boot.bin').write_bytes(self.combined.read_bytes())
        written = prepare_ctxr.prepare(esp, esp)
        self.assertIn('boot-ctxr.bin', written)
        self.assertEqual((esp / 'boot-ctxr.bin').read_bytes(), (esp / 'boot.bin').read_bytes())
        self.assertEqual((esp / 'boot-ctxr-j700.bin').read_bytes(), (esp / 'boot-j700.bin').read_bytes())
        self.assertFalse((esp / 'boot-ctxr-j274.bin').exists())

    def test_prepare_stage2_output_must_precede_the_ctxr_files(self):
        esp = self.root / 'esp/m1n1'
        self.split(esp)
        (esp / 'boot.bin').write_bytes(self.combined.read_bytes())
        prepare_ctxr.prepare(esp, esp)
        with self.assertRaises(ValueError):
            self.split(esp)

    def test_a_second_run_replaces_what_the_first_wrote(self):
        esp = self.root / 'esp/m1n1'
        self.split(esp)
        (esp / 'boot.bin').write_bytes(self.combined.read_bytes())
        prepare_ctxr.prepare(esp, esp)
        (esp / 'boot.bin').write_bytes(b'rebuilt combined')
        prepare_ctxr.prepare(esp, esp)
        self.assertEqual((esp / 'boot-ctxr.bin').read_bytes(), b'rebuilt combined')

    def test_an_oversized_shared_file_is_refused(self):
        esp = self.root / 'esp/m1n1'
        self.split(esp)
        (esp / 'boot.bin').write_bytes(b'\0' * (prepare_ctxr.MAX_STAGE2_BYTES + 1))
        with self.assertRaises(ValueError):
            prepare_ctxr.prepare(esp, esp)

    def test_required_board_missing_is_refused(self):
        boards = self.root / 'boards'
        self.split(boards)
        (boards / 'boot-j616s.bin').unlink()
        with self.assertRaises(ValueError):
            prepare_ctxr.prepare(boards, self.root / 'ctxr')

    def test_chip_list_matches_the_installer(self):
        for chip in MACHO_CHIPS:
            self.assertTrue(prepare_ctxr.uses_macho([f'apple,{chip}']), chip)
        for chip in EARLIER_CHIPS:
            self.assertFalse(prepare_ctxr.uses_macho([f'apple,{chip}']), chip)

    def test_image_build_adds_the_ctxr_files_after_the_board_files(self):
        text = (ROOT / 'scripts/build-image').read_text()
        self.assertLess(text.index('prepare-stage2.py'), text.index('prepare-ctxr-stage2.py'))
        self.assertLess(text.index('prepare-ctxr-stage2.py'), text.index('-filesystems.tar.zst'))

    def test_image_build_adds_the_ctxr_files_only_with_the_marker(self):
        text = (ROOT / 'scripts/build-image').read_text()
        self.assertIn('if [[ -e $aura/share/aura/monitor-free ]]; then\n'
                      '  python3 "$root/scripts/prepare-ctxr-stage2.py"', text)
        self.assertEqual(text.count('prepare-ctxr-stage2.py'), 1)

    def test_the_installed_build_splits_boards_only_with_the_marker(self):
        text = (ROOT / 'modules/installed.nix').read_text()
        marker = text.index('if [[ -e ${aura}/share/aura/monitor-free ]]; then')
        self.assertLess(marker, text.index('touch $out/monitor-free'))
        self.assertLess(marker, text.index('scripts/build-ctxr-stage2.sh}'))

    def flag(self, name):
        return re.search(rf'(?m)^  {name} = (true|false);$', (ROOT / 'overlay.nix').read_text())[1] == 'true'

    def step(self, start, end):
        """The lines of overlay.nix from the one starting `start` to the next one equal to `end`."""
        text = (ROOT / 'overlay.nix').read_text()
        return re.search(rf'(?ms)^ +{re.escape(start)}.*?^ +{re.escape(end)}$', text)[0]

    def test_an_aura_without_the_monitor_needs_a_kernel_that_keeps_its_code_in_the_window(self):
        # Both flags are checked against the pinned source and the resolved
        # configuration when they build, and evaluation asserts the pair.
        if self.flag('auraMonitorFree'):
            self.assertTrue(self.flag('kernelCtxrExecmem'),
                            'aura without the monitor needs CONFIG_ARM64_CTXR_EXECMEM=y')
        self.assertIn('CONFIG_ARM64_CTXR_EXECMEM=y', (ROOT / 'kernel/config').read_text().splitlines())
        self.assertIn('final.lib.assertMsg (auraMonitorFree -> kernelCtxrExecmem)',
                      (ROOT / 'overlay.nix').read_text())

    def test_a_system_checks_the_kernel_it_boots_against_its_aura(self):
        # Not just the two constants: a system that overrides its kernel is checked too.
        overlay = (ROOT / 'overlay.nix').read_text()
        self.assertIn('auroraCtxrExecmem = kernelCtxrExecmem;', overlay)
        self.assertIn('passthru = (old.passthru or { }) // { auroraMonitorFree = auraMonitorFree; };', overlay)
        installed = (ROOT / 'modules/installed.nix').read_text()
        self.assertIn('assertion = !(aura.auroraMonitorFree or false)\n'
                      '        || (config.boot.kernelPackages.kernel.auroraCtxrExecmem or false);', installed)

    def test_nix_reports_the_option_only_once_the_kernel_has_it(self):
        # kernel/config names it early and Kconfig drops it, so kernel.config.isYes
        # must not see it until kernelCtxrExecmem says the build resolves it.
        overlay = (ROOT / 'overlay.nix').read_text()
        self.assertIn('(final.lib.optional (!kernelCtxrExecmem) "CONFIG_ARM64_CTXR_EXECMEM");', overlay)
        self.assertIn('kernelConfig = builtins.removeAttrs', overlay)

    def test_the_kernel_build_refuses_a_flag_its_configuration_disagrees_with(self):
        check = self.step('ctxr=false', 'fi')
        for line, value, ok in (('CONFIG_ARM64_CTXR_EXECMEM=y', 'true', True), ('', 'false', True),
                                ('CONFIG_ARM64_CTXR_EXECMEM=y', 'false', False), ('', 'true', False)):
            with self.subTest(line=line, value=value), tempfile.TemporaryDirectory() as temporary:
                (Path(temporary) / '.config').write_text(line + '\n')
                script = check.replace('${final.lib.boolToString kernelCtxrExecmem}', value)
                result = subprocess.run(['bash', '-euc', script], capture_output=True, text=True,
                                        env=dict(os.environ, buildRoot=temporary))
                self.assertEqual(result.returncode == 0, ok, result.stderr)

    def test_the_aura_build_refuses_a_flag_the_pinned_source_disagrees_with(self):
        check = self.step('found=false', 'fi')
        marker = '${final.lib.optionalString auraMonitorFree "touch $out/share/aura/monitor-free"}'
        self.assertIn(marker, (ROOT / 'overlay.nix').read_text())
        cases = {'monitor': (('monitor.c',), False), 'monitor-free': (('ctxr_exec.c',), True),
                 'both': (('monitor.c', 'ctxr_exec.c'), True), 'renamed': (('other.c',), True)}
        for name, (files, source) in cases.items():
            for value in (False, True):
                with self.subTest(name, value=value), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    (root / 'src').mkdir()
                    for file in files:
                        (root / 'src' / file).write_text('')
                    script = check.replace('${final.lib.boolToString auraMonitorFree}', str(value).lower())
                    result = subprocess.run(['bash', '-euc', script], cwd=root, capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, value == source, result.stderr)


class BuildCtxrStage2Tests(unittest.TestCase):
    AURA = b'AURA-STAGE2-BINARY'
    BOARDS = {'j274': 't8103', 'j700': 't8140', 'j616s': 't6040', 'j614s': 't6040', 'j713': 't8132'}

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.aura = self.root / 'aura.bin'
        self.aura.write_bytes(self.AURA)
        self.output = self.root / 'ctxr'

    def run_build(self, boards=None, padding=None, aura=None):
        padding = padding or {}
        trees = b''.join(full_device_tree(board, chip, padding.get(board, 0))
                         for board, chip in (boards or self.BOARDS).items())
        combined = self.root / 'boot.bin'
        combined.write_bytes((aura or self.AURA) + trees + gzip.compress(b'u-boot', mtime=0))
        scripts = ROOT / 'scripts'
        return subprocess.run(['bash', str(scripts / 'build-ctxr-stage2.sh'), str(scripts / 'check-stage2.py'),
                               str(scripts / 'prepare-stage2.py'), str(scripts / 'prepare-ctxr-stage2.py'),
                               str(combined), str(self.aura), str(self.output)],
                              capture_output=True, text=True, env=dict(os.environ, TMPDIR=str(self.root)))

    def built(self):
        return sorted(path.name for path in self.output.iterdir()) if self.output.is_dir() else []

    def test_each_macho_board_gets_its_file_and_digest(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.built(), [f'boot-ctxr-{board}{suffix}' for board in ('j614s', 'j616s', 'j700', 'j713')
                                        for suffix in ('.bin', '.bin.sha256')])
        image = (self.output / 'boot-ctxr-j700.bin').read_bytes()
        self.assertEqual(check_stage2.check(image, self.AURA, ['j700'])['boards'], ['apple,j700'])
        self.assertEqual((self.output / 'boot-ctxr-j700.bin.sha256').read_text().strip(), hashlib.sha256(image).hexdigest())

    def test_a_missing_macho_board_does_not_stop_a_rebuild(self):
        result = self.run_build(boards={'j274': 't8103', 'j713': 't8132'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.built(), ['boot-ctxr-j713.bin', 'boot-ctxr-j713.bin.sha256'])

    def test_a_macho_board_over_the_limit_is_left_out_and_warned_about(self):
        result = self.run_build(padding={'j700': prepare_ctxr.MAX_STAGE2_BYTES})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('boot-j700.bin', result.stderr)
        self.assertNotIn('boot-ctxr-j700.bin', self.built())
        self.assertIn('boot-ctxr-j713.bin', self.built())

    def test_a_stage2_that_cannot_be_split_does_not_stop_a_rebuild(self):
        result = self.run_build(aura=b'SOME-OTHER-AURA-BUILD')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('could not split', result.stderr)
        self.assertEqual([name for name in self.built() if name.endswith('.bin')], [])


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
