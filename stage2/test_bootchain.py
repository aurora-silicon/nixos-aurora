import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bootchain', Path(os.environ.get('BOOTCHAIN_MODULE', PACKAGE / 'bootchain.py')))
bootchain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootchain)


@unittest.skipUnless(shutil.which('dtc') and shutil.which('fdtget'), 'requires dtc')
class BootchainTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = {'TARGET': '/esp/m1n1/boot.bin'}
        self.put('/usr/lib64/m1n1/m1n1.bin', b'AURA')
        self.put('/usr/share/uboot/apple_m1/u-boot-nodtb.bin', b'U-BOOT')
        self.target = self.put('/esp/m1n1/boot.bin', b'GOOD-STAGE2')
        self.backup = self.put('/esp/m1n1/boot.bin.old', b'OLDER-STAGE2')
        self.put('/boot/dtb-known/apple/t8112-j413.dtb', self.dtb('j413', 1))
        self.link = self.root / 'boot/dtb'
        self.link.symlink_to('dtb-known')

    def put(self, path, content):
        path = self.root / path.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def dtb(self, board, cells):
        dts = f'''/dts-v1/; / {{ compatible = "apple,{board}", "apple,t8112";
                  dart {{ compatible = "apple,t8110-dart"; #iommu-cells = <{cells}>; }}; }};'''
        return subprocess.check_output(['dtc', '-q', '-I', 'dts', '-O', 'dtb'], input=dts.encode())

    def kernel(self, version, cells=1, board='j413', generation=1):
        self.put(f'/usr/lib/modules/{version}/vmlinuz', version.encode())
        if generation is not None:
            self.put(f'/usr/lib/modules/{version}/dtb-abi', f'{generation}\n'.encode())
        return self.put(f'/usr/lib/modules/{version}/dtb/apple/t8112-{board}.dtb', self.dtb(board, cells))

    def action(self, action, version):
        self.env.update(AURORA_KERNEL_ACTION=action, AURORA_KERNEL_VERSION=version)

    def apply(self):
        bootchain.Update(self.root, self.env).apply()

    def unchanged(self):
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.backup.read_bytes(), b'OLDER-STAGE2')
        self.assertEqual(os.readlink(self.link), 'dtb-known')

    def test_retained_one_cell_and_new_five_cell_refuses_each_machine(self):
        for board in ('j316s', 'j413', 'j700'):
            with self.subTest(board=board):
                self.kernel('7.1', 1, board, generation=0)
                self.kernel('7.3', 5, board)
                self.put('/proc/device-tree/compatible', f'apple,{board}\0'.encode())
                self.action('add', '7.3')
                with self.assertRaisesRegex(bootchain.Refused, r'retained kernels 7.1 \(generation 0\)'):
                    self.apply()
                self.unchanged()

    def test_different_same_generation_dtbs_accepts_fallback_and_keeps_backup(self):
        self.kernel('7.1')
        blob = self.kernel('7.3', 5).read_bytes()
        self.action('add', '7.3')
        self.apply()
        payload = self.target.read_bytes()
        self.assertTrue(payload.startswith(b'AURA' + blob))
        self.assertEqual(gzip.decompress(payload[4 + len(blob):]), b'U-BOOT')
        self.assertEqual(self.backup.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(os.readlink(self.link), 'dtb-7.3')
        self.assertTrue(self.link.is_dir())
        self.assertEqual((self.link / 'apple/t8112-j413.dtb').read_bytes(), blob)
        self.apply()
        self.assertEqual(self.backup.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.target.read_bytes(), payload)

    def test_fallback_removal_allows_new_tree(self):
        self.kernel('7.1', 1)
        new = self.kernel('7.3', 5).read_bytes()
        self.action('remove', '7.1')
        self.apply()
        self.assertTrue(self.target.read_bytes().startswith(b'AURA' + new))
        self.assertEqual(os.readlink(self.link), 'dtb-7.3')

    def test_missing_dtb_refuses_without_partial_file_or_dangling_link(self):
        self.kernel('7.1')
        self.put('/usr/lib/modules/7.3/vmlinuz', b'new kernel')
        self.action('add', '7.3')
        with self.assertRaisesRegex(bootchain.Refused, 'no DTB directory'):
            self.apply()
        self.unchanged()
        self.assertFalse(list(self.target.parent.glob('.boot.bin.*')))
        self.assertFalse(self.target.with_name('boot.bin.new').exists())

    def test_missing_fallback_dtbs_also_refuses(self):
        self.kernel('7.3', 5)
        self.put('/boot/vmlinuz-7.1', b'fallback')
        with self.assertRaisesRegex(bootchain.Refused, 'no DTB directory'):
            self.apply()
        self.unchanged()

    def test_invalid_dtb_refuses(self):
        self.kernel('7.3').write_bytes(b'not a DTB')
        with self.assertRaisesRegex(bootchain.Refused, 'invalid DTB'):
            self.apply()
        self.unchanged()

    def test_empty_dtb_directory_refuses(self):
        self.kernel('7.3').unlink()
        with self.assertRaisesRegex(bootchain.Refused, 'no Apple DTBs'):
            self.apply()
        self.unchanged()

    def test_missing_uboot_refuses_before_any_writes(self):
        self.kernel('7.3')
        (self.root / 'usr/share/uboot/apple_m1/u-boot-nodtb.bin').unlink()
        with self.assertRaises(FileNotFoundError):
            self.apply()
        self.unchanged()

    def test_real_boot_dtb_directory_is_preserved(self):
        self.kernel('7.3')
        self.link.unlink()
        self.link.mkdir()
        with self.assertRaisesRegex(bootchain.Refused, 'not a symlink'):
            self.apply()
        self.assertTrue(self.link.is_dir())
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

    def test_stage2_symlink_is_preserved(self):
        self.kernel('7.3')
        self.target.unlink()
        self.target.symlink_to('boot.bin.old')
        with self.assertRaisesRegex(bootchain.Refused, 'target is a symlink'):
            self.apply()
        self.assertEqual(self.backup.read_bytes(), b'OLDER-STAGE2')

    def test_failed_fsync_preserves_live_stage2_backup_and_link(self):
        self.kernel('7.3')
        with patch.object(bootchain.os, 'fsync', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.apply()
        self.unchanged()

    def test_failure_before_live_rename_keeps_live_stage2_and_link(self):
        self.kernel('7.3')
        original = bootchain.os.replace
        def replace(source, destination):
            if destination == self.target:
                raise OSError('interrupted before commit')
            return original(source, destination)
        with patch.object(bootchain.os, 'replace', side_effect=replace):
            with self.assertRaises(OSError):
                self.apply()
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.backup.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(os.readlink(self.link), 'dtb-known')
        self.assertFalse(list(self.target.parent.glob('.boot.bin.*')))

    def test_failure_after_live_rename_has_complete_image_and_old_link(self):
        self.kernel('7.3')
        original = bootchain.os.replace
        def replace(source, destination):
            if destination == self.link:
                raise OSError('interrupted after Stage 2 commit')
            return original(source, destination)
        with patch.object(bootchain.os, 'replace', side_effect=replace):
            with self.assertRaises(OSError):
                self.apply()
        self.assertTrue(self.target.read_bytes().startswith(b'AURA'))
        self.assertEqual(self.backup.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(os.readlink(self.link), 'dtb-known')
        self.assertTrue(self.link.is_dir())
        self.apply()  # A retry repairs the link without changing the backup.
        self.assertEqual(os.readlink(self.link), 'dtb-7.3')
        self.assertEqual(self.backup.read_bytes(), b'GOOD-STAGE2')

    def test_same_generation_allows_unrelated_board_changes(self):
        self.kernel('7.1', 1, 'j413')
        self.kernel('7.3', 1, 'j413')
        self.kernel('7.1', 1, 'j700')
        self.kernel('7.3', 5, 'j700')
        self.put('/proc/device-tree/compatible', b'apple,j413\0apple,t8112\0')
        self.apply()
        self.assertEqual(os.readlink(self.link), 'dtb-7.3')

    def test_image_build_accepts_different_same_generation_sets(self):
        self.kernel('7.1', 1, 'j413')
        self.kernel('7.3', 1, 'j413')
        self.kernel('7.3', 5, 'j700')
        self.apply()
        self.assertEqual(os.readlink(self.link), 'dtb-7.3')

    def selected_blob(self):
        payload = self.target.read_bytes()
        self.assertTrue(payload.startswith(b'AURA'))
        return payload

    def test_refresh_uses_saved_entry_default_not_newer_test_kernel(self):
        default = self.kernel('7.3.0-aurora-fleet37', 5).read_bytes()
        self.kernel('7.3.0-aurora-tb3c', 1)
        self.put('/boot/loader/entries/abc-7.3.0-aurora-fleet37.conf', b'title x\nversion 7.3.0-aurora-fleet37\n')
        self.put('/boot/grub2/grubenv', b'# GRUB Environment Block\nsaved_entry=abc-7.3.0-aurora-fleet37\n####\n')
        self.apply()
        self.assertTrue(self.selected_blob().startswith(b'AURA' + default))
        self.assertEqual(os.readlink(self.link), 'dtb-7.3.0-aurora-fleet37')

    def test_custom_cfg_default_wins_over_stale_saved_entry(self):
        default = self.kernel('7.3.0-aurora-fleet42', 5).read_bytes()
        self.kernel('7.3.0-aurora-sepkey3', 1)
        self.kernel('7.3.0-aurora-fleet41', 1)
        self.put('/boot/grub2/grubenv', b'saved_entry=aurora-ref-7.3.0-aurora-fleet41\n')
        self.put('/boot/grub2/custom.cfg', b'if [ "${boot_once}" != "true" ]; then\n'
                 b'  set default="aurora-ref-7.3.0-aurora-fleet42"\nfi\n')
        self.apply()
        self.assertTrue(self.selected_blob().startswith(b'AURA' + default))
        self.assertEqual(os.readlink(self.link), 'dtb-7.3.0-aurora-fleet42')

    def test_unknown_default_falls_back_to_newest(self):
        self.kernel('7.1', 1)
        newest = self.kernel('7.3', 5).read_bytes()
        self.put('/boot/grub2/grubenv', b'saved_entry=abc-6.9-removed\n')
        self.apply()
        self.assertTrue(self.selected_blob().startswith(b'AURA' + newest))

    def test_numeric_grub_default_counts_from_newest(self):
        older = self.kernel('7.1', 1).read_bytes()
        self.kernel('7.3', 5)
        self.put('/etc/default/grub', b'GRUB_DEFAULT=1\n')
        self.apply()
        self.assertTrue(self.selected_blob().startswith(b'AURA' + older))

    def test_add_follows_updatedefault(self):
        self.kernel('7.1', 1)
        added = self.kernel('7.3', 5).read_bytes()
        self.put('/boot/loader/entries/abc-7.1.conf', b'version 7.1\n')
        self.put('/boot/grub2/grubenv', b'saved_entry=abc-7.1\n')
        self.action('add', '7.3')
        self.apply()  # UPDATEDEFAULT=yes (Fedora's default): the new kernel becomes the default.
        self.assertTrue(self.selected_blob().startswith(b'AURA' + added))

    def test_add_without_updatedefault_keeps_default_kernel(self):
        default = self.kernel('7.1', 1).read_bytes()
        self.kernel('7.3', 5)
        self.put('/boot/loader/entries/abc-7.1.conf', b'version 7.1\n')
        self.put('/boot/grub2/grubenv', b'saved_entry=abc-7.1\n')
        self.put('/etc/sysconfig/kernel', b'UPDATEDEFAULT=no\n')
        self.action('add', '7.3')
        self.apply()
        self.assertTrue(self.selected_blob().startswith(b'AURA' + default))
        self.assertEqual(os.readlink(self.link), 'dtb-7.1')

    def test_add_under_custom_cfg_default_keeps_pinned_kernel(self):
        default = self.kernel('7.3.0-aurora-fleet37', 5).read_bytes()
        self.kernel('7.3.0-aurora-tb3c', 1)
        self.put('/boot/grub2/custom.cfg', b'set default="aurora-ref-7.3.0-aurora-fleet37"\n')
        self.action('add', '7.3.0-aurora-tb3c')
        self.apply()
        self.assertTrue(self.selected_blob().startswith(b'AURA' + default))

    def test_missing_current_board_refuses(self):
        self.kernel('7.3')
        self.put('/proc/device-tree/compatible', b'apple,j700\0')
        with self.assertRaisesRegex(bootchain.Refused, 'have no apple,j700'):
            self.apply()
        self.unchanged()

    def test_custom_dtbs_do_not_bypass_retained_kernel_check(self):
        self.kernel('7.3', 5)
        self.env['DTBS'] = '/boot/dtb-known'
        with self.assertRaisesRegex(bootchain.Refused, 'custom DTBS have no installed DT ABI source'):
            self.apply()
        self.unchanged()

    def test_orphan_bls_kernel_is_not_ignored(self):
        self.kernel('7.3')
        self.put('/boot/loader/entries/old.conf', b'version 7.1\nlinux /vmlinuz-7.1\n')
        with self.assertRaisesRegex(bootchain.Refused, 'image missing'):
            self.apply()
        self.unchanged()

    def test_rescue_copy_uses_original_tree_but_unknown_rescue_refuses(self):
        self.kernel('7.3')
        self.put('/usr/lib/modules/0-rescue-test/dtb-abi', b'1\n')
        rescue = self.put('/boot/vmlinuz-0-rescue-test', b'7.3')
        self.apply()
        rescue.write_bytes(b'unknown old kernel')
        with self.assertRaisesRegex(bootchain.Refused, 'no provable DTB source'):
            self.apply()

    def test_remove_last_kernel_preserves_stage2(self):
        self.kernel('7.3')
        self.action('remove', '7.3')
        with self.assertRaisesRegex(bootchain.Refused, 'no remaining'):
            self.apply()
        self.unchanged()

    def test_existing_versioned_dtbs_are_not_overwritten(self):
        self.kernel('7.3', 5)
        self.put('/boot/dtb-7.3/apple/t8112-j413.dtb', self.dtb('j413', 1))
        with self.assertRaisesRegex(bootchain.Refused, 'differs from'):
            self.apply()
        self.unchanged()

    def test_kernel_version_cannot_escape_paths(self):
        self.action('add', '../../outside')
        with self.assertRaisesRegex(bootchain.Refused, 'invalid kernel version'):
            self.apply()

    def test_multiple_variants_for_one_board_are_preserved_and_checked(self):
        first = self.kernel('7.3').read_bytes()
        variant = self.put('/usr/lib/modules/7.3/dtb/apple/t8112-j413-variant.dtb', self.dtb('j413', 5))
        self.apply()
        payload = self.target.read_bytes()
        self.assertIn(first, payload)
        self.assertIn(variant.read_bytes(), payload)
        self.kernel('7.1')
        self.put('/proc/device-tree/compatible', b'apple,j413\0')
        self.apply()
        self.assertIn(variant.read_bytes(), self.target.read_bytes())

    def test_explicit_globs_keep_legacy_configuration(self):
        self.kernel('7.3')
        self.env['DTBS'] = '/usr/lib/modules/7.3/dtb/apple/t6*.dtb /usr/lib/modules/7.3/dtb/apple/t81*.dtb'
        self.put('/usr/lib/modules/7.3/dtb/apple/t6000-j316s.dtb', self.dtb('j316s', 1))
        self.apply()

    def test_process_death_before_live_rename_keeps_bootable_file(self):
        self.kernel('7.3')
        code = '''import importlib.util, json, os, pathlib, signal, sys
s = importlib.util.spec_from_file_location('updater', sys.argv[1])
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
root = pathlib.Path(sys.argv[2]); env = json.loads(sys.argv[3])
original = m.os.replace
def replace(source, destination):
    if destination == root / 'esp/m1n1/boot.bin':
        os.kill(os.getpid(), signal.SIGKILL)
    return original(source, destination)
m.os.replace = replace
m.Update(root, env).apply()
'''
        result = subprocess.run([sys.executable, '-c', code, str(Path(os.environ.get('BOOTCHAIN_MODULE', PACKAGE / 'bootchain.py'))),
                                 str(self.root), json.dumps(self.env)], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, -9, result.stderr.decode())
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.backup.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(os.readlink(self.link), 'dtb-known')
        self.assertTrue(list(self.target.parent.glob('.boot.bin.*')))
        self.apply()
        self.assertTrue(self.target.read_bytes().startswith(b'AURA'))
        self.assertTrue(self.link.is_dir())

    def test_empty_custom_dtb_setting_refuses(self):
        self.kernel('7.3')
        self.env['DTBS'] = ''
        with self.assertRaisesRegex(bootchain.Refused, 'unset or empty'):
            self.apply()
        self.unchanged()

    def test_firmware_dtb_policy_removes_link_only_after_success(self):
        self.kernel('7.3')
        self.env['AURORA_FIRMWARE_DT'] = 'True'
        self.apply()
        self.assertFalse(self.link.is_symlink())
        self.assertTrue(self.target.read_bytes().startswith(b'AURA'))

    def test_failed_firmware_dtb_update_keeps_previous_link(self):
        self.kernel('7.3', 5)
        self.kernel('7.1', 1, generation=0)
        self.env['AURORA_FIRMWARE_DT'] = 'True'
        with self.assertRaises(bootchain.Refused):
            self.apply()
        self.unchanged()

    def test_remove_cleanup_drops_only_link_to_erased_version(self):
        self.link.unlink()
        self.link.symlink_to('dtb-7.1')
        self.action('remove', '7.1')
        bootchain.Update(self.root, self.env).cleanup_remove()
        self.assertFalse(self.link.is_symlink())
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.backup.read_bytes(), b'OLDER-STAGE2')

    def test_remove_cleanup_preserves_other_kernel_link(self):
        self.action('remove', '7.1')
        bootchain.Update(self.root, self.env).cleanup_remove()
        self.unchanged()

    def test_remove_cleanup_cannot_be_used_during_add(self):
        self.action('add', '7.3')
        with self.assertRaisesRegex(bootchain.Refused, 'requires a remove'):
            bootchain.Update(self.root, self.env).cleanup_remove()
        self.unchanged()

    def test_missing_marker_is_generation_zero_and_refuses_newer_dtbs(self):
        self.kernel('7.1', generation=None)
        self.kernel('7.3')
        with self.assertRaisesRegex(bootchain.Refused, r'7.1 \(generation 0\)'):
            self.apply()
        self.unchanged()

    def test_missing_markers_allow_generation_zero_even_with_different_bytes(self):
        self.kernel('7.1', generation=None)
        self.kernel('7.3', 5, generation=None)
        self.apply()
        self.assertEqual(os.readlink(self.link), 'dtb-7.3')

    def test_higher_retained_generation_allows_lower_selected_generation(self):
        self.kernel('7.1', generation=2)
        self.kernel('7.3', 5, generation=1)
        self.apply()
        self.assertEqual(os.readlink(self.link), 'dtb-7.3')

    def test_generation_bump_refuses_even_identical_bytes_and_lists_all_older_kernels(self):
        self.kernel('7.1', generation=0)
        self.kernel('7.2', generation=1)
        self.kernel('7.3', generation=2)
        with self.assertRaises(bootchain.Refused) as result:
            self.apply()
        message = str(result.exception)
        self.assertIn('DT ABI generation 2', message)
        self.assertIn('7.1 (generation 0), 7.2 (generation 1)', message)
        self.assertIn("sudo dnf remove '/usr/lib/modules/7.1/vmlinuz' '/usr/lib/modules/7.2/vmlinuz'", message)
        self.assertIn('sudo update-m1n1', message)
        self.assertNotIn('\n', message)
        self.unchanged()
        self.assertTrue((self.root / 'usr/lib/modules/7.1/vmlinuz').exists())

    def test_generation_numbers_compare_numerically(self):
        self.kernel('7.1', generation=2)
        self.kernel('7.3', generation=10)
        with self.assertRaisesRegex(bootchain.Refused, 'generation 10'):
            self.apply()
        self.unchanged()

    def test_invalid_markers_refuse_before_writes(self):
        self.kernel('7.3')
        for value in (b'', b'-1\n', b'1 2\n', b'1\n2\n', b'garbage', b'01\n', b'1\n\n'):
            with self.subTest(value=value):
                self.put('/usr/lib/modules/7.3/dtb-abi', value)
                with self.assertRaisesRegex(bootchain.Refused, 'invalid DT ABI generation'):
                    self.apply()
                self.unchanged()

    def test_retained_invalid_marker_is_not_ignored(self):
        self.kernel('7.1')
        self.kernel('7.3')
        self.put('/usr/lib/modules/7.1/dtb-abi', b'unknown')
        with self.assertRaisesRegex(bootchain.Refused, 'invalid DT ABI generation for kernel 7.1'):
            self.apply()
        self.unchanged()

    def test_custom_dtbs_keep_their_own_generation_check(self):
        self.kernel('7.1', generation=0)
        self.kernel('7.3', 5, generation=1)
        self.env['DTBS'] = '/usr/lib/modules/7.3/dtb'
        with self.assertRaisesRegex(bootchain.Refused, r'7.1 \(generation 0\)'):
            self.apply()
        self.unchanged()

    def test_custom_older_tree_uses_its_declared_generation(self):
        old = self.kernel('7.1', generation=0).read_bytes()
        self.kernel('7.3', 5, generation=1)
        self.env['DTBS'] = '/usr/lib/modules/7.1/dtb'
        self.apply()
        self.assertTrue(self.target.read_bytes().startswith(b'AURA' + old))

    def test_invalid_custom_dtbs_refuse(self):
        self.kernel('7.3')
        self.env['DTBS'] = '/boot/dtb-known'
        self.put('/boot/dtb-known/apple/t8112-j413.dtb', b'broken')
        with self.assertRaisesRegex(bootchain.Refused, 'invalid DTB'):
            self.apply()
        self.unchanged()

    def test_rescue_without_marker_is_generation_zero(self):
        self.kernel('7.3')
        self.put('/boot/vmlinuz-0-rescue-test', b'7.3')
        with self.assertRaisesRegex(bootchain.Refused, r'0-rescue-test \(generation 0\)'):
            self.apply()
        self.unchanged()

    def test_selected_marker_without_final_newline_is_valid(self):
        self.kernel('7.3')
        self.put('/usr/lib/modules/7.3/dtb-abi', b'1')
        self.apply()
        self.assertEqual(os.readlink(self.link), 'dtb-7.3')


class TrialTests(unittest.TestCase):
    setUp = BootchainTests.setUp
    put = BootchainTests.put
    dtb = BootchainTests.dtb
    kernel = BootchainTests.kernel
    apply = BootchainTests.apply
    unchanged = BootchainTests.unchanged
    def trial_setup(self):
        self.env.update(ESP_ROOT='/esp', ESP_DEVICE='/dev/test-esp', ESP_FSTYPE='vfat')
        self.put('/proc/device-tree/compatible', b'apple,j413\0apple,t8112\0')
        self.put('/proc/device-tree/chosen/asahi,m1n1-stage1-version', b'1.0.0b4\0')
        self.kernel('7.3')
        self.candidate = self.target.with_name('boot.bin.next')
        self.marker = self.root / 'esp/aura-try'
        self.prev = self.target.with_name('boot.bin.prev')
        self.addCleanup(patch.stopall)
        patch.object(bootchain.Update, 'check_esp').start()
        self.flush = patch.object(bootchain.Update, 'flush_esp').start()

    def trial_boot(self):
        self.marker.write_bytes(b'spent\nm1n1/boot.bin.next\n')
        self.put('/proc/device-tree/chosen/aurora,trial', b'm1n1/boot.bin.next\0')

    def commit(self):
        bootchain.Update(self.root, self.env).commit()

    def ordinary_boot(self):
        (self.root / 'proc/device-tree/chosen/aurora,trial').unlink(missing_ok=True)

    def attempt(self, payload):
        return self.root / 'var/lib/aurora-stage2/attempts' / hashlib.sha256(payload).hexdigest()

    def sane(self):
        self.put('/sys/kernel/debug/devices_deferred', b'')
        self.put('/proc/device-tree/soc/dcp/compatible', b'apple,t8112-dcp\0')
        platform = self.root / 'sys/bus/platform/devices/dcp'
        platform.mkdir(parents=True)
        (platform / 'of_node').symlink_to(self.root / 'proc/device-tree/soc/dcp')
        driver = self.root / 'sys/bus/platform/drivers/dcp'
        driver.mkdir(parents=True)
        (platform / 'driver').symlink_to(driver)
        original = bootchain.subprocess.check_output
        def output(command, **kwargs):
            if command[0] == 'findmnt':
                return '/dev/nvme0n1p6[/root]\n'
            if command[0] == 'lsblk':
                return 'nvme0n1p6\nnvme0n1\n'
            return original(command, **kwargs)
        patch.object(bootchain.subprocess, 'check_output', side_effect=output).start()

    def ctxr_setup(self):
        self.trial_setup()
        self.put('/usr/share/aura/monitor-free', b'')
        self.put('/proc/device-tree/compatible', b'apple,j700\0apple,t8140\0')
        self.kernel('7.3', board='j700')
        self.ctxr = self.put('/esp/m1n1/boot-ctxr.bin', b'GOOD-CTXR')
        self.candidate = self.ctxr.with_name('boot-ctxr.bin.next')

    def test_ctxr_trial_keeps_both_live_slots(self):
        self.ctxr_setup()
        self.apply()
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot-ctxr.bin.next\n')
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.ctxr.read_bytes(), b'GOOD-CTXR')
        self.assertIn(self.dtb('j700', 1), self.candidate.read_bytes())
        self.assertNotIn(self.dtb('j413', 1), self.candidate.read_bytes())

    def test_ctxr_commit_replaces_only_the_ctxr_slot(self):
        self.ctxr_setup()
        self.apply()
        payload = self.candidate.read_bytes()
        self.marker.write_bytes(b'spent\nm1n1/boot-ctxr.bin.next\n')
        self.put('/proc/device-tree/chosen/aurora,trial', b'm1n1/boot-ctxr.bin.next\0')
        self.sane()
        self.commit()
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.ctxr.read_bytes(), payload)
        self.assertEqual(self.ctxr.with_name('boot-ctxr.bin.prev').read_bytes(), b'GOOD-CTXR')
        self.assertFalse(self.marker.exists())

    def test_trial_armed_without_commit(self):
        self.trial_setup()
        self.apply()
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')
        self.assertTrue(self.candidate.read_bytes().startswith(b'AURA'))
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertFalse(self.prev.exists())
        self.assertEqual(self.backup.read_bytes(), b'OLDER-STAGE2')
        self.assertTrue(self.attempt(self.candidate.read_bytes()).exists())
        self.assertEqual(os.readlink(self.link), 'dtb-7.3')
        self.commit()  # Still on the ordinary boot that staged it.
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

    def test_commit_on_trial_boot(self):
        self.trial_setup()
        self.apply()
        payload = self.candidate.read_bytes()
        self.trial_boot()
        self.sane()
        self.commit()
        self.assertEqual(self.target.read_bytes(), payload)
        self.assertEqual(self.prev.read_bytes(), b'GOOD-STAGE2')
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.candidate.exists())
        self.apply()  # Package triggers on the same boot do not rearm.
        self.assertFalse(self.marker.exists())

    def test_fallback_keeps_live_and_never_rearms_this_kernel(self):
        self.trial_setup()
        self.apply()
        payload = self.candidate.read_bytes()
        self.marker.write_bytes(b'spent\nm1n1/boot.bin.next\n')
        with patch('builtins.print') as log:
            self.commit()
        self.assertEqual(log.call_count, 1)
        self.assertIn('fell back', log.call_args[0][0])
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.candidate.read_bytes(), payload)
        self.apply()
        self.assertTrue(self.marker.read_bytes().startswith(b'spent\n'))

    def test_same_kernel_boot_input_updates_trial_after_commit(self):
        # aura, U-Boot and m1n1.conf updates keep the kernel but are new candidates.
        self.trial_setup()
        self.sane()
        self.apply()
        self.trial_boot()
        self.commit()
        self.ordinary_boot()
        for path, content in (('/usr/lib64/m1n1/m1n1.bin', b'AURA-2'),
                              ('/usr/share/uboot/apple_m1/u-boot-nodtb.bin', b'U-BOOT-2'),
                              ('/etc/m1n1.conf', b'display=1920x1080\n')):
            with self.subTest(path=path):
                live = self.target.read_bytes()
                self.put(path, content)
                self.apply()
                self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')
                self.assertEqual(self.target.read_bytes(), live)
                payload = self.candidate.read_bytes()
                self.assertNotEqual(payload, live)
                self.trial_boot()
                self.commit()
                self.ordinary_boot()
                self.assertEqual(self.target.read_bytes(), payload)
                self.assertFalse(self.marker.exists())
        self.assertTrue(self.target.read_bytes().startswith(b'AURA-2'))
        self.assertTrue(self.target.read_bytes().endswith(b'display=1920x1080\n'))

    def test_reverted_committed_candidate_may_trial_again(self):
        self.trial_setup()
        self.sane()
        self.apply()
        first = self.candidate.read_bytes()
        self.trial_boot()
        self.commit()
        self.ordinary_boot()
        self.assertEqual(json.loads(self.attempt(first).read_text())['result'], 'committed')
        self.put('/usr/lib64/m1n1/m1n1.bin', b'AURA-2')
        self.apply()
        self.trial_boot()
        self.commit()
        self.ordinary_boot()
        self.put('/usr/lib64/m1n1/m1n1.bin', b'AURA')
        self.apply()
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')
        self.assertEqual(self.candidate.read_bytes(), first)
        self.assertNotIn('result', json.loads(self.attempt(first).read_text()))

    def test_fallen_back_candidate_is_never_rearmed_but_a_new_one_is(self):
        self.trial_setup()
        self.apply()
        failed = self.candidate.read_bytes()
        self.marker.write_bytes(b'spent\nm1n1/boot.bin.next\n')
        self.commit()  # Stage 1 fell back to the live image.
        self.put('/usr/lib64/m1n1/m1n1.bin', b'AURA-2')
        self.apply()
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')
        self.assertTrue(self.candidate.read_bytes().startswith(b'AURA-2'))
        saved = self.target.with_name('boot.bin.failed-' + hashlib.sha256(failed).hexdigest())
        self.assertEqual(saved.read_bytes(), failed)
        self.marker.write_bytes(b'spent\nm1n1/boot.bin.next\n')
        self.put('/usr/lib64/m1n1/m1n1.bin', b'AURA')
        with patch('builtins.print') as log:
            self.apply()  # Reverting to the failed candidate does not retry it.
        self.assertIn('already attempted', log.call_args_list[0][0][0])
        self.assertEqual(self.marker.read_bytes(), b'spent\nm1n1/boot.bin.next\n')
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

    def test_committed_trial_boot_accepts_package_updates(self):
        self.trial_setup()
        self.sane()
        self.apply()
        self.trial_boot()
        self.commit()
        committed = self.target.read_bytes()
        self.put('/usr/lib64/m1n1/m1n1.bin', b'AURA-2')
        self.apply()  # Same boot, after the commit removed the marker.
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')
        self.assertEqual(self.target.read_bytes(), committed)
        staged = self.candidate.read_bytes()
        self.assertTrue(staged.startswith(b'AURA-2'))
        self.apply()  # A repeated trigger with the same inputs changes nothing.
        self.assertEqual(self.candidate.read_bytes(), staged)
        self.put('/usr/lib64/m1n1/m1n1.bin', b'AURA-3')
        with self.assertRaisesRegex(bootchain.Refused, 'already armed'):
            self.apply()
        self.assertEqual(self.candidate.read_bytes(), staged)
        with patch.object(bootchain.subprocess, 'run') as command:
            bootchain.Update(self.root, self.env).guard()
        command.assert_not_called()
        self.commit()  # The new candidate waits for its own trial boot.
        self.assertEqual(self.target.read_bytes(), committed)
        self.assertTrue(self.marker.exists())

    def test_trial_without_its_marker_can_no_longer_commit_and_is_kept(self):
        self.trial_setup()
        self.apply()
        self.trial_boot()
        abandoned = self.candidate.read_bytes()
        self.marker.unlink()  # Removed by hand: commit() can no longer publish it.
        self.kernel('7.4', cells=5)
        self.apply()
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')
        saved = self.target.with_name('boot.bin.failed-' + hashlib.sha256(abandoned).hexdigest())
        self.assertEqual(saved.read_bytes(), abandoned)
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

    def test_kernel_keyed_attempt_still_blocks_its_fallen_back_candidate(self):
        self.trial_setup()
        self.apply()
        payload = self.candidate.read_bytes()
        self.attempt(payload).rename(self.root / 'var/lib/aurora-stage2/attempts/7.3')
        self.marker.write_bytes(b'spent\nm1n1/boot.bin.next\n')
        self.apply()
        self.assertEqual(self.marker.read_bytes(), b'spent\nm1n1/boot.bin.next\n')
        self.put('/usr/lib64/m1n1/m1n1.bin', b'AURA-2')
        self.apply()  # The kernel version alone no longer blocks a new candidate.
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')

    def test_kernel_keyed_attempt_commits_and_is_rekeyed(self):
        self.trial_setup()
        self.sane()
        self.apply()
        payload = self.candidate.read_bytes()
        legacy = self.root / 'var/lib/aurora-stage2/attempts/7.3'
        self.attempt(payload).rename(legacy)
        self.trial_boot()
        self.commit()
        self.assertEqual(self.target.read_bytes(), payload)
        self.assertFalse(legacy.exists())
        self.assertEqual(json.loads(self.attempt(payload).read_text())['result'], 'committed')

    def test_old_stage1_direct_replace_and_backup(self):
        self.trial_setup()
        self.put('/proc/device-tree/chosen/asahi,m1n1-stage1-version', b'1.0.0b3\0')
        self.apply()
        self.assertTrue(self.target.read_bytes().startswith(b'AURA'))
        self.assertEqual(self.backup.read_bytes(), b'GOOD-STAGE2')
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.candidate.exists())

    def test_trial_generation_refusal_precedes_all_esp_writes(self):
        self.trial_setup()
        self.kernel('7.1', generation=0)
        with self.assertRaisesRegex(bootchain.Refused, 'generation 0'):
            self.apply()
        self.unchanged()
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.candidate.exists())

    def test_version_detection(self):
        self.trial_setup()
        update = bootchain.Update(self.root, self.env)
        for version, expected in [('1.0.0b3', False), ('1.0.0b4', True), ('1.0.0b4-dirty', True),
                                  ('1.0.0b5-gabcd1234', True), ('1.0.0b5-gabcd1234-dirty', True),
                                  ('1.0.0', True), ('1.6.1', False), ('unknown', False)]:
            self.put('/proc/device-tree/chosen/asahi,m1n1-stage1-version', version.encode() + b'\0')
            self.assertEqual(update.supports_trial(), expected, version)
        self.put('/proc/device-tree/chosen/aura,stage1-version', b'2.0.0\0')
        self.assertTrue(update.supports_trial())

    def test_display_alias_required_in_board_tree(self):
        self.trial_setup()
        self.put('/proc/device-tree/aliases/dcp', b'/soc/dcp\0')
        # Another board's valid alias cannot satisfy this Mac's requirement.
        other = subprocess.check_output(['dtc', '-q', '-I', 'dts', '-O', 'dtb'], input=b'''/dts-v1/;
/ { compatible = "apple,j316s", "apple,t6000";
aliases { dcp = "/dcp"; }; dcp {}; };''')
        self.put('/usr/lib/modules/7.3/dtb/apple/t6000-j316s.dtb', other)
        with self.assertRaisesRegex(bootchain.Refused, 'display alias dcp'):
            self.apply()
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

    def test_board_tree_display_aliases_pass(self):
        self.trial_setup()
        self.put('/proc/device-tree/aliases/dcp', b'/soc/dcp\0')
        self.put('/proc/device-tree/aliases/disp0', b'/soc/display\0')
        blob = subprocess.check_output(['dtc', '-q', '-I', 'dts', '-O', 'dtb'], input=b'''
/dts-v1/; / { compatible = "apple,j413", "apple,t8112";
aliases { dcp = "/soc/dcp"; disp0 = "/soc/display"; };
soc { dcp {}; display {}; }; };''')
        self.put('/usr/lib/modules/7.3/dtb/apple/t8112-j413.dtb', blob)
        self.apply()
        self.assertTrue(self.marker.exists())

    def test_corrupt_candidate_cannot_commit(self):
        self.trial_setup()
        self.apply()
        self.trial_boot()
        self.candidate.write_bytes(b'corrupt')
        with self.assertRaisesRegex(bootchain.Refused, 'changed since'):
            self.commit()
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertFalse(self.prev.exists())

    def test_no_candidate_overwrite_during_trial(self):
        self.trial_setup()
        self.apply()
        self.trial_boot()
        before = self.candidate.read_bytes()
        self.kernel('7.4', cells=5)
        with self.assertRaisesRegex(bootchain.Refused, 'trial is running'):
            self.apply()
        self.assertEqual(self.candidate.read_bytes(), before)

    def test_foreign_marker_preserved(self):
        self.trial_setup()
        self.marker.write_bytes(b'armed\nother/image.bin\n')
        with self.assertRaisesRegex(bootchain.Refused, 'another aura-try'):
            self.apply()
        self.assertEqual(self.marker.read_bytes(), b'armed\nother/image.bin\n')
        self.assertFalse(self.candidate.exists())

    def test_new_kernel_preserves_previous_trial_evidence(self):
        self.trial_setup()
        self.apply()
        before = self.candidate.read_bytes()
        self.marker.write_bytes(b'spent\nm1n1/boot.bin.next\n')
        self.kernel('7.4', cells=5)
        self.apply()
        saved = list(self.target.parent.glob('boot.bin.failed-*'))
        self.assertTrue(any(p.read_bytes() == before for p in saved))
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')

    def test_missing_debugfs_or_unbound_dcp_refuses_commit(self):
        self.trial_setup()
        self.apply()
        self.trial_boot()
        self.sane()
        (self.root / 'sys/kernel/debug/devices_deferred').unlink()
        with self.assertRaises(FileNotFoundError):
            self.commit()
        self.put('/sys/kernel/debug/devices_deferred', b'')
        (self.root / 'sys/bus/platform/devices/dcp/driver').unlink()
        with self.assertRaisesRegex(bootchain.Refused, 'DCP is not bound'):
            self.commit()
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertTrue(self.candidate.exists())

    def test_deferred_dt_device_refuses_but_non_dt_device_allows(self):
        self.trial_setup()
        self.apply()
        self.trial_boot()
        self.sane()
        self.put('/sys/kernel/debug/devices_deferred', b'dcp\tplatform: waiting for supplier\n')
        with self.assertRaisesRegex(bootchain.Refused, 'DT device still deferred'):
            self.commit()
        self.put('/sys/kernel/debug/devices_deferred', b'non-dt-device\n')
        self.commit()
        self.assertFalse(self.marker.exists())

    def test_non_nvme_root_refuses_commit(self):
        self.trial_setup()
        self.apply()
        self.trial_boot()
        with patch.object(bootchain.subprocess, 'check_output', side_effect=['/dev/sda1\n', 'sda1\nsda\n']):
            with self.assertRaisesRegex(bootchain.Refused, 'root is not mounted on NVMe'):
                bootchain.Update(self.root, self.env).sanity()
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

    def test_failed_marker_flush_never_changes_live_or_rearms(self):
        self.trial_setup()
        self.flush.side_effect = OSError('injected flush failure')
        with self.assertRaisesRegex(OSError, 'flush failure'):
            self.apply()
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.flush.side_effect = None
        self.apply()
        self.assertFalse(self.marker.exists())

    def test_kernel_added_after_arming_cannot_bypass_generation_guard(self):
        self.trial_setup()
        self.apply()
        self.trial_boot()
        self.kernel('7.1', generation=0)
        with self.assertRaisesRegex(bootchain.Refused, 'retained kernels now require an older'):
            self.commit()
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertFalse(self.prev.exists())

    def test_uncommitted_trial_guard_reboots_to_fallback(self):
        self.trial_setup()
        self.apply()
        self.trial_boot()
        with patch.object(bootchain.subprocess, 'run') as command:
            bootchain.Update(self.root, self.env).guard()
        command.assert_called_once_with(['systemctl', '--no-block', 'reboot'], check=True)
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

    def test_committed_trial_guard_does_not_reboot(self):
        self.trial_setup()
        self.apply()
        self.trial_boot()
        self.sane()
        self.commit()
        with patch.object(bootchain.subprocess, 'run') as command:
            bootchain.Update(self.root, self.env).guard()
        command.assert_not_called()

    def test_commit_flush_failure_restores_live_and_keeps_candidate(self):
        self.trial_setup()
        self.apply()
        self.trial_boot()
        self.sane()
        payload = self.candidate.read_bytes()
        self.flush.side_effect = [None, OSError('commit flush failure'), None]
        with self.assertRaisesRegex(OSError, 'commit flush failure'):
            self.commit()
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.candidate.read_bytes(), payload)
        self.assertEqual(self.prev.read_bytes(), b'GOOD-STAGE2')
        self.assertTrue(self.marker.exists())

    def test_marker_is_renamed_only_after_fsynced_candidate_and_receipt(self):
        self.trial_setup()
        original = bootchain.os.replace
        def replace(source, destination):
            if destination == self.marker:
                self.assertEqual(Path(source).name, 'aura-try.tmp')
                self.assertTrue(self.candidate.exists())
                self.assertTrue(self.target.with_name('boot.bin.next.json').exists())
                self.assertTrue(self.attempt(self.candidate.read_bytes()).exists())
                self.assertGreater(self.flush.call_count, 0)
                self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
            original(source, destination)
        with patch.object(bootchain.os, 'replace', side_effect=replace):
            self.apply()


if __name__ == '__main__':
    unittest.main()
