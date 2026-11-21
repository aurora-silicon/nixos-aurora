import contextlib
import functools
import gzip
import hashlib
import importlib.util
import io
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

    def test_bls_entry_whose_kernel_is_gone_is_ignored(self):
        # As a migrated J493 had: the Asahi kernel was removed, its entry was not.
        self.kernel('7.3')
        old = 'abc-7.1.6-400.asahi.fc44.aarch64+16k.conf'
        self.put(f'/boot/loader/entries/{old}',
                 b'version 7.1.6-400.asahi.fc44.aarch64+16k\nlinux /vmlinuz-7.1.6-400.asahi.fc44.aarch64+16k\n')
        self.apply()
        self.assertEqual(os.readlink(self.link), 'dtb-7.3')

    def test_bls_entry_whose_kernel_is_elsewhere_still_refuses(self):
        self.kernel('7.3')
        self.put('/boot/loader/entries/abc-7.3.conf', b'version 7.3\nlinux /vmlinuz-7.3\n')
        self.put('/boot/grub2/grubenv', b'saved_entry=abc-7.3\n')
        self.put('/boot/images/vmlinuz-7.1', b'7.1')
        self.put('/boot/loader/entries/old.conf', b'version 7.1\nlinux /images/vmlinuz-7.1\n')
        with self.assertRaisesRegex(bootchain.Refused, 'image missing'):
            self.apply()
        self.unchanged()

    def test_bls_entry_without_a_kernel_line_still_refuses(self):
        self.kernel('7.3')
        self.put('/boot/loader/entries/old.conf', b'version 7.1\n')
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

    def test_missing_marker_is_generation_one(self):
        # A kernel from before the marker kept every later kernel off a J493.
        self.kernel('7.1', generation=None)
        self.kernel('7.3')
        self.apply()
        self.assertEqual(os.readlink(self.link), 'dtb-7.3')

    def test_missing_marker_still_refuses_a_later_generation(self):
        self.kernel('7.1', generation=None)
        self.kernel('7.3', generation=2)
        with self.assertRaisesRegex(bootchain.Refused, r'7.1 \(generation 1\)'):
            self.apply()
        self.unchanged()

    def test_missing_markers_allow_one_generation_even_with_different_bytes(self):
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

    def test_rescue_without_marker_is_generation_one(self):
        self.kernel('7.3')
        self.put('/boot/vmlinuz-0-rescue-test', b'7.3')
        self.apply()
        self.assertEqual(os.readlink(self.link), 'dtb-7.3')

    def test_rescue_without_marker_refuses_a_later_generation(self):
        self.kernel('7.3', generation=2)
        self.put('/boot/vmlinuz-0-rescue-test', b'7.3')
        with self.assertRaisesRegex(bootchain.Refused, r'0-rescue-test \(generation 1\)'):
            self.apply()
        self.unchanged()

    def test_selected_marker_without_final_newline_is_valid(self):
        self.kernel('7.3')
        self.put('/usr/lib/modules/7.3/dtb-abi', b'1')
        self.apply()
        self.assertEqual(os.readlink(self.link), 'dtb-7.3')


@unittest.skipUnless(shutil.which('dtc') and shutil.which('fdtget'), 'requires dtc')
class SigningTests(unittest.TestCase):
    setUp = BootchainTests.setUp
    put = BootchainTests.put
    dtb = BootchainTests.dtb
    kernel = BootchainTests.kernel
    apply = BootchainTests.apply

    def signer(self, body):
        path = self.put('/usr/bin/aurora-secboot', f'#!{sys.executable}\n{body}'.encode())
        path.chmod(0o755)
        return path

    def test_without_aurora_secboot_the_stage2_is_unsigned(self):
        self.kernel('7.3')
        self.apply()
        self.assertTrue(self.target.read_bytes().startswith(b'AURA'))
        self.assertNotIn(b'AURSIGT1', self.target.read_bytes())

    def test_the_signer_output_is_written(self):
        self.kernel('7.3')
        self.signer('import sys\n'
                    'assert sys.argv[1:3] == ["stage2", "hook"]\n'
                    'data = open(sys.argv[3], "rb").read()\n'
                    'open(sys.argv[4], "wb").write(data + b"SIG" + b"AURSIGT1")\n'
                    'print("aurora-secboot: Stage 2 signed")\n')
        self.apply()
        data = self.target.read_bytes()
        self.assertTrue(data.startswith(b'AURA') and data.endswith(b'SIGAURSIGT1'))
        self.assertEqual(self.root.joinpath('esp/m1n1/boot.bin.old').read_bytes(), b'GOOD-STAGE2')

    def test_a_failed_signer_keeps_the_live_stage2(self):
        self.kernel('7.3')
        self.signer('import sys\nprint("aurora-secboot: there is no stage2.key", file=sys.stderr)\nsys.exit(1)\n')
        with self.assertRaisesRegex(bootchain.Refused, 'Stage 2 signing failed: aurora-secboot: there is no stage2.key'):
            self.apply()
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(os.readlink(self.link), 'dtb-known')

    def test_a_signer_that_changes_the_image_is_refused(self):
        self.kernel('7.3')
        self.signer('import sys\nopen(sys.argv[4], "wb").write(b"OTHER")\n')
        with self.assertRaisesRegex(bootchain.Refused, 'changed the composed image'):
            self.apply()
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

    def test_signer_path_comes_from_the_environment(self):
        self.kernel('7.3')
        self.signer('import sys\nsys.exit(1)\n')
        self.env['AURORA_STAGE2_SIGNER'] = '/nonexistent/aurora-secboot'
        self.apply()
        self.assertTrue(self.target.read_bytes().startswith(b'AURA'))


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

    def test_trial_candidate_is_the_signed_stage2(self):
        self.trial_setup()
        signer = self.put('/usr/bin/aurora-secboot', f'#!{sys.executable}\nimport sys\n'
                          'data = open(sys.argv[3], "rb").read()\n'
                          'open(sys.argv[4], "wb").write(data + b"SIG" + b"AURSIGT1")\n'.encode())
        signer.chmod(0o755)
        self.apply()
        candidate = self.candidate.read_bytes()
        self.assertTrue(candidate.endswith(b'SIGAURSIGT1'))
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        receipt = json.loads(self.candidate.with_name('boot.bin.next.json').read_text())
        self.assertEqual(receipt['sha256'], hashlib.sha256(candidate).hexdigest())

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
                                  ('1.0.0b13.1', True), ('1.0.0b13.1-g5dcf62d0', True),
                                  ('1.0.0', True), ('1.6.1', False), ('unknown', False)]:
            self.put('/proc/device-tree/chosen/asahi,m1n1-stage1-version', version.encode() + b'\0')
            self.assertEqual(update.supports_trial(), expected, version)
        # aura#313 renames the property; Stage 2 writes the old name too until 2027-02-28.
        self.put('/proc/device-tree/chosen/aurora,aura-stage1-version', b'1.6.1\0')
        self.assertTrue(update.supports_trial())
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

    def soc_siblings(self, first_soc, plain_soc):
        # T6050 has soc@200000000, soc@2308000000 and soc; fdtget -p resolves
        # /soc to the first soc@... sibling.
        self.trial_setup()
        self.put('/proc/device-tree/aliases/dcp', b'/soc/dcp@48ae00000\0')
        dts = f'''/dts-v1/; / {{ compatible = "apple,j413", "apple,t8112";
aliases {{ dcp = "/soc/dcp@48ae00000"; }};
soc@200000000 {{ {first_soc} }}; soc@2308000000 {{}}; soc {{ {plain_soc} }}; }};'''
        blob = subprocess.check_output(['dtc', '-q', '-I', 'dts', '-O', 'dtb'], input=dts.encode())
        self.put('/usr/lib/modules/7.3/dtb/apple/t8112-j413.dtb', blob)

    def test_display_alias_node_under_unit_less_soc(self):
        self.soc_siblings(first_soc='', plain_soc='dcp@48ae00000 { reg = <1>; };')
        self.apply()
        self.assertTrue(self.marker.exists())

    def test_display_alias_node_under_other_soc(self):
        self.soc_siblings(first_soc='dcp@48ae00000 { reg = <1>; };', plain_soc='')
        with self.assertRaisesRegex(bootchain.Refused, 'display alias dcp has no node'):
            self.apply()
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

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

    def test_foreign_trial_boot_is_skipped_by_commit(self):
        # A trial armed by hand with aura-try, booted: commit skips it cleanly.
        self.trial_setup()
        self.marker.write_bytes(b'spent\nother/image.bin\n')
        self.put('/proc/device-tree/chosen/aurora,trial', b'other/image.bin\0')
        with patch('builtins.print') as log:
            self.commit()
        self.assertEqual(log.call_count, 1)
        self.assertIn('not managed here', log.call_args[0][0])
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.marker.read_bytes(), b'spent\nother/image.bin\n')
        self.assertFalse(self.candidate.exists())
        bootchain.Update(self.root, self.env).guard()  # not this updater's trial: no reboot

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


class Stage1PathTests(unittest.TestCase):
    """Stage 2 is written only where this boot's Stage 1 loads it, and never older (#452)."""
    setUp = BootchainTests.setUp
    put = BootchainTests.put
    dtb = BootchainTests.dtb
    kernel = BootchainTests.kernel
    trial_setup = TrialTests.trial_setup
    trial_boot = TrialTests.trial_boot
    commit = TrialTests.commit
    sane = TrialTests.sane
    attempt = TrialTests.attempt

    PACKAGED = b'AURA##aura_ver##1.0.0b13-g3c491419\0'

    def setup(self, stage1='1.0.0b13-g3d517e63'):
        self.trial_setup()
        self.put('/usr/lib64/m1n1/m1n1.bin', self.PACKAGED)
        self.stage1(stage1)
        self.receipt = self.target.with_name('boot.bin.next.json')

    def j713_setup(self):
        """The #452 Air: a CTXR board whose Stage 1 loads aura/stage2.bin, a lab Stage 2."""
        self.setup()
        self.put('/usr/share/aura/monitor-free', b'')
        self.put('/proc/device-tree/compatible', b'apple,j713\0apple,t8132\0')
        self.kernel('7.3', board='j713')
        self.ctxr = self.put('/esp/m1n1/boot-ctxr.bin', b'IMAGE-CTXR##aura_ver##1.0.0b13-g3c491419\0')
        self.lab = self.put('/esp/aura/stage2.bin', b'LAB-STAGE2##aura_ver##1.0.0b13-gc0a50c00\0')
        self.running('1.0.0b13-gc0a50c00')
        self.loaded(self.lab.read_bytes())

    def stage1(self, version):
        self.put('/proc/device-tree/chosen/asahi,m1n1-stage1-version', version.encode() + b'\0')

    def running(self, version):
        self.put('/proc/device-tree/chosen/asahi,m1n1-stage2-version', version.encode() + b'\0')

    def loaded(self, data=None, *, digest=None, raw=False, index=0, stage='stage1', component='next-stage'):
        """This boot's record of the image Stage 1 loaded, as aura's secboot.c hands it to Linux."""
        digest = hashlib.sha256(data).digest() if digest is None else digest
        if raw:  # A Stage 2 older than 1.0.0b12 keeps Stage 1's line as a plain chosen property.
            self.put(f'/proc/device-tree/chosen/aurora,measure-{index}',
                     f'{stage};none;{component};unsigned;0000000000000000;0;{digest.hex()}\0'.encode())
            return
        node = f'/proc/device-tree/chosen/aurora,boot-security/measurement@{index}'
        for name, value in (('stage', stage), ('policy', 'none'), ('component', component),
                            ('verdict', 'unsigned')):
            self.put(f'{node}/{name}', value.encode() + b'\0')
        self.put(f'{node}/sha256', digest)

    def esp(self):
        esp = self.root / 'esp'
        return {p.relative_to(esp).as_posix(): p.read_bytes() for p in sorted(esp.rglob('*')) if p.is_file()}

    def hook(self, **env):
        """apply() as the hook runs it: (stdout, stderr). A refusal here is a test failure."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            bootchain.Update(self.root, dict(self.env, **env)).apply()
        return out.getvalue(), err.getvalue()

    def assert_kept(self, before, message):
        out, err = self.hook()
        self.assertEqual(self.esp(), before)
        self.assertFalse(self.marker.exists())
        attempts = self.root / 'var/lib/aurora-stage2/attempts'
        self.assertFalse(attempts.exists() and list(attempts.iterdir()))
        self.assertIn(message, err)
        self.assertIn('not touching the boot chain', err)
        self.assertNotIn('Stage 2 verified', out)
        self.assertIn('Stage 2 left unchanged', out)
        return out, err

    def assert_armed(self, name='boot.bin'):
        self.assertEqual(self.marker.read_bytes(), f'armed\nm1n1/{name}.next\n'.encode())
        self.assertTrue(self.target.with_name(name + '.next').read_bytes().startswith(self.PACKAGED))

    def test_stage1_loading_another_file_arms_nothing(self):
        self.j713_setup()
        before = self.esp()
        _, err = self.assert_kept(before, 'Stage 1 loads aura/stage2.bin, not m1n1/boot-ctxr.bin')
        self.assertEqual(self.lab.read_bytes(), b'LAB-STAGE2##aura_ver##1.0.0b13-gc0a50c00\0')
        # The kernel is still installed: its DTBs and /boot/dtb follow it as for a candidate not rearmed.
        self.assertEqual(os.readlink(self.link), 'dtb-7.3')

    def test_stage1_loading_the_target_arms_the_trial(self):
        self.setup()
        self.loaded(self.target.read_bytes())
        self.hook()
        self.assert_armed()
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

    def test_stage1_loading_the_ctxr_slot_arms_its_trial(self):
        self.j713_setup()
        self.loaded(self.ctxr.read_bytes())
        self.hook()
        self.assert_armed('boot-ctxr.bin')
        self.assertEqual(self.ctxr.read_bytes(), b'IMAGE-CTXR##aura_ver##1.0.0b13-g3c491419\0')

    def test_a_signed_target_is_compared_without_its_trailer(self):
        self.setup()
        body = b'GOOD-STAGE2'
        self.target.write_bytes(body + b'aura_sig' + bytes(104) + len(body).to_bytes(8, 'little') + b'AURSIGT1')
        self.loaded(body)
        self.hook()
        self.assert_armed()

    def test_a_malformed_trailer_is_hashed_whole(self):
        self.setup()
        self.target.write_bytes(b'GOOD-STAGE2' + (99).to_bytes(8, 'little') + b'AURSIGT1')
        self.loaded(b'GOOD-STAGE2')
        self.assert_kept(self.esp(), 'not m1n1/boot.bin')

    def test_a_raw_record_line_from_an_older_stage2_is_read(self):
        self.setup()
        self.loaded(self.target.read_bytes(), raw=True)
        self.loaded(b'U-Boot', stage='stage2', component='payload')  # Stage 2's own entries do not count.
        self.hook()
        self.assert_armed()

    def test_a_raw_record_of_another_file_arms_nothing(self):
        self.setup()
        self.put('/esp/aurora/stage2.bin', b'ELSEWHERE')
        self.loaded(b'ELSEWHERE', raw=True)
        self.assert_kept(self.esp(), 'Stage 1 loads aurora/stage2.bin, not m1n1/boot.bin')

    def test_an_image_on_no_file_of_this_esp_arms_nothing(self):
        self.setup()
        self.loaded(b'not on the ESP')
        self.assert_kept(self.esp(), 'matches no file on this ESP')

    def test_a_missing_target_is_not_created(self):
        self.setup()
        self.loaded(self.target.read_bytes())
        self.target.unlink()
        self.assert_kept(self.esp(), 'not m1n1/boot.bin')

    def test_a_stage1_that_records_but_left_no_record_changes_nothing(self):
        for version in ('1.0.0b12', '1.0.0b13-g3d517e63', '1.0.0b13.1'):
            with self.subTest(version=version):
                self.setUp()
                self.setup(version)
                self.loaded(b'U-Boot', stage='stage2', component='payload')
                self.assert_kept(self.esp(), f'Stage 1 {version} records the Stage 2 it loads')

    def test_an_unusable_or_ambiguous_record_changes_nothing(self):
        for case in ('short', 'two'):
            with self.subTest(case=case):
                self.setUp()
                self.setup()
                if case == 'short':
                    self.loaded(digest=bytes(31))
                else:
                    self.loaded(self.target.read_bytes())
                    self.loaded(b'other', index=1)
                self.assert_kept(self.esp(), 'cannot be shown to load m1n1/boot.bin')

    def test_commit_then_a_new_kernel_on_the_same_trial_boot_arms_it(self):
        self.setup()
        self.loaded(self.target.read_bytes())
        self.hook()
        payload = self.target.with_name('boot.bin.next').read_bytes()
        self.trial_boot()
        self.loaded(payload)  # The trial boot's Stage 1 loaded the candidate.
        self.sane()
        self.commit()
        self.assertEqual(self.target.read_bytes(), payload)
        self.kernel('7.4', cells=2)
        self.env.update(AURORA_KERNEL_ACTION='add', AURORA_KERNEL_VERSION='7.4')
        self.hook()
        self.assert_armed()
        self.assertEqual(json.loads(self.receipt.read_text())['kernel'], '7.4')

    def test_another_tools_trial_boot_arms_nothing(self):
        self.setup()
        lab = self.put('/esp/m1n1/lab.bin', b'LAB')
        self.put('/proc/device-tree/chosen/aurora,trial', b'm1n1/lab.bin\0')
        self.loaded(lab.read_bytes())
        self.assert_kept(self.esp(), 'this boot is an aura-try trial of m1n1/lab.bin')

    def test_an_older_stage1_running_another_stage2_changes_nothing(self):
        # nixos-aurora#282's J614s: Stage 1 1.0.0b5 kept loading boot.bin (b5) while b10 went to boot-ctxr.bin.
        self.setup('1.0.0b5')
        self.target.write_bytes(b'AURA##aura_ver##1.0.0b10-gbd9f3e82\0')
        self.running('1.0.0b5')
        self.assert_kept(self.esp(), 'Stage 2 1.0.0b5 booted, but m1n1/boot.bin holds aura 1.0.0b10-gbd9f3e82')

    def test_an_older_stage1_without_a_target_changes_nothing(self):
        self.setup('1.0.0b5')
        self.target.unlink()
        self.running('1.0.0b5')
        self.assert_kept(self.esp(), 'm1n1/boot.bin does not exist')

    def test_an_older_stage1_running_the_target_arms_the_trial(self):
        self.setup('1.0.0b11')
        self.target.write_bytes(b'AURA##aura_ver##1.0.0b11-geca16db0\0')
        self.running('1.0.0b11-geca16db0')
        self.hook()
        self.assert_armed()

    def test_an_older_stage1_without_versions_keeps_the_installer_layout(self):
        self.setup('1.0.0b4')  # Neither the running Stage 2 nor GOOD-STAGE2 names a version.
        self.hook()
        self.assert_armed()

    def test_an_older_candidate_is_not_armed(self):
        self.setup()
        self.loaded(self.target.read_bytes())
        self.running('1.0.0b13-gc0a50c00')
        self.put('/usr/lib64/m1n1/m1n1.bin', b'AURA##aura_ver##1.0.0b12-gea20cedb\0')
        self.assert_kept(self.esp(), 'aura 1.0.0b12-gea20cedb is older than the running Stage 2 1.0.0b13-gc0a50c00')

    def test_a_forced_downgrade_is_armed_but_still_only_where_stage1_loads(self):
        self.setup()
        self.running('1.0.0b13-gc0a50c00')
        self.put('/usr/lib64/m1n1/m1n1.bin', b'AURA##aura_ver##1.0.0b12-gea20cedb\0')
        self.loaded(b'not on the ESP')
        _, err = self.hook(AURORA_STAGE2_ALLOW_DOWNGRADE='1')
        self.assertFalse(self.marker.exists())
        self.assertIn('matches no file on this ESP', err)
        self.loaded(self.target.read_bytes())
        self.hook(AURORA_STAGE2_ALLOW_DOWNGRADE='1')
        self.assertTrue(self.marker.read_bytes().startswith(b'armed\n'))

    def test_order_unknown_or_newer_is_not_a_downgrade(self):
        for running, packaged in (('1.0.0b13-gc0a50c00', '1.0.0b13-g3c491419'),  # same release
                                  ('1.0.0b13-gf0f180af', '1.0.0b13.1'),
                                  ('1.0.0b12', '1.0.0b13-g5dcf62d0-dirty'),
                                  ('v1.4.21', '1.0.0b13'),  # Asahi's m1n1: another project's numbers
                                  ('', '1.0.0b13')):
            with self.subTest(running=running, packaged=packaged):
                self.setUp()
                self.setup()
                self.loaded(self.target.read_bytes())
                if running:
                    self.running(running)
                self.PACKAGED = f'AURA##aura_ver##{packaged}\0'.encode()
                self.put('/usr/lib64/m1n1/m1n1.bin', self.PACKAGED)
                self.hook()
                self.assert_armed()

    def test_a_point_release_is_newer_than_its_beta(self):
        self.setup()
        self.loaded(self.target.read_bytes())
        self.running('1.0.0b13.1')
        self.put('/usr/lib64/m1n1/m1n1.bin', b'AURA##aura_ver##1.0.0b13-g5dcf62d0\0')
        self.assert_kept(self.esp(), 'older than the running Stage 2 1.0.0b13.1')

    def test_a_downgrade_is_not_written_by_direct_replacement_either(self):
        self.setup('1.0.0b3')  # No aura-try: the live file is replaced in place.
        self.running('1.0.0b13')
        self.put('/usr/lib64/m1n1/m1n1.bin', b'AURA##aura_ver##1.0.0b12\0')
        self.assert_kept(self.esp(), 'older than the running Stage 2 1.0.0b13')

    def test_a_trial_armed_for_a_file_stage1_does_not_load_is_withdrawn(self):
        # Armed by an updater without these checks, never booted: disarm it before the next boot.
        self.setup('1.0.0b11')
        self.hook()
        candidate = self.target.with_name('boot.bin.next').read_bytes()
        self.assertTrue(self.attempt(candidate).exists())
        self.stage1('1.0.0b13-g3d517e63')
        self.put('/esp/aura/stage2.bin', b'LAB')
        self.loaded(b'LAB')
        out, err = self.hook()
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.target.with_name('boot.bin.next').exists())
        self.assertFalse(self.receipt.exists())
        self.assertFalse(self.attempt(candidate).exists())
        self.assertIn('withdrawn before it was booted: Stage 1 loads aura/stage2.bin, not m1n1/boot.bin', out)
        self.assertIn('not touching the boot chain', err)
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

    def test_an_armed_downgrade_is_withdrawn(self):
        self.setup()
        self.loaded(self.target.read_bytes())
        self.hook()
        self.running('1.0.0b14')
        out, _ = self.hook()
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.target.with_name('boot.bin.next').exists())
        self.assertIn('withdrawn before it was booted', out)

    def test_a_foreign_marker_is_never_touched(self):
        self.setup()
        self.marker.write_bytes(b'armed\nm1n1/lab.bin\n')
        self.loaded(b'not on the ESP')
        with self.assertRaisesRegex(bootchain.Refused, 'another aura-try'):
            self.hook()
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/lab.bin\n')

    def test_a_running_trial_is_still_refused_first(self):
        self.setup()
        self.loaded(b'not on the ESP')
        self.trial_boot()
        with self.assertRaisesRegex(bootchain.Refused, 'a trial is running'):
            self.hook()

    def test_aura_release_order(self):
        order = ['1.0.0b4', '1.0.0b12-gea20cedb', '1.0.0b13', '1.0.0b13.1-g5dcf62d0', '1.0.0b14-dirty',
                 '1.0.0', '1.0.1b1', 'aura v1.1.0']
        releases = [bootchain.aura_release(version) for version in order]
        self.assertEqual(releases, sorted(releases))
        self.assertEqual(len(set(releases)), len(releases))
        self.assertEqual(bootchain.aura_release('1.0.0b13-gc0a50c00'), bootchain.aura_release('1.0.0b13-g3c491419'))
        for other in ('v1.4.21', '1.5.0', 'unknown', ''):
            self.assertIsNone(bootchain.aura_release(other), other)
        self.assertEqual(bootchain.aura_release('1.5.0', aura=True), (1, 5, 0, 1, 0, 0))

    def test_aura_tag_comes_from_the_version_marker(self):
        self.assertEqual(bootchain.aura_tag(b'x##aura_ver##1.0.0b13-g3c491419\0rest'), '1.0.0b13-g3c491419')
        self.assertIsNone(bootchain.aura_tag(b'##m1n1_ver##v1.4.21\0'))
        self.assertIsNone(bootchain.aura_tag(b'##aura_ver##bad tag\0'))


class DtbNodesTests(unittest.TestCase):
    @staticmethod
    def blob(*tokens):
        struct = b''.join(tokens)
        # Only off_dt_struct (bytes 8-12) is read; the structure follows the header.
        return b'\xd0\x0d\xfe\xed' + bytes(4) + (40).to_bytes(4, 'big') + bytes(28) + struct

    @staticmethod
    def token(value, data=b''):
        data += bytes(-len(data) % 4)
        return value.to_bytes(4, 'big') + data

    def test_nodes_skip_nop_and_properties(self):
        begin, end, prop, nop = (bootchain.FDT_BEGIN_NODE, bootchain.FDT_END_NODE,
                                 bootchain.FDT_PROP, bootchain.FDT_NOP)
        blob = self.blob(self.token(begin, b'\0'), self.token(nop),
                         self.token(begin, b'soc@200000000\0'), self.token(end),
                         self.token(begin, b'soc\0'),
                         self.token(prop, (5).to_bytes(4, 'big') + bytes(4) + b'abcde'),
                         self.token(nop), self.token(begin, b'dcp@48ae00000\0'),
                         self.token(end), self.token(end), self.token(end),
                         self.token(bootchain.FDT_END))
        self.assertEqual(bootchain.dtb_nodes(blob),
                         {'/', '/soc@200000000', '/soc', '/soc/dcp@48ae00000'})

    def test_unknown_token_refused(self):
        blob = self.blob(self.token(bootchain.FDT_BEGIN_NODE, b'\0'), self.token(7),
                         self.token(bootchain.FDT_END_NODE), self.token(bootchain.FDT_END))
        with self.assertRaisesRegex(bootchain.Refused, 'invalid Stage 2 DTB structure'):
            bootchain.dtb_nodes(blob)


class GrubOrderTests(unittest.TestCase):
    def test_version_comparison_is_rpms(self):
        for a, b, expected in [('1.0', '1.0', 0), ('1.0', '2.0', -1), ('2.0.1', '2.0', 1),
                               ('5.5p1', '5.5p2', -1), ('5.5p10', '5.5p1', 1), ('10xyz', '10.1xyz', -1),
                               ('1.0aa', '1.0a', 1), ('010', '10', 0), ('1.0~rc1', '1.0', -1),
                               ('1.0~rc1', '1.0~rc2', -1), ('1.0+git1', '1.0', 1), ('1.0', '1.0+git1', -1),
                               ('40.fc44.aurora.aarch64', 'neo.test1', 1)]:
            with self.subTest(a=a, b=b):
                self.assertEqual(bootchain.grub_vercmp(a, b), expected)
                self.assertEqual(bootchain.grub_vercmp(b, a), -expected)

    def test_grub_lists_releases_above_the_local_kernels_sort_v_put_first(self):
        versions = ['7.3.0-neo.final', '7.3.0-39.fc44.aurora.aarch64', '7.3.0-40.fc44.aurora.aarch64',
                    '7.3.0-neo.test1', '7.3.0-26.fc44.aurora.aarch64']
        ids = sorted((f'abc-{v}' for v in versions), key=functools.cmp_to_key(bootchain.grub_entry_cmp),
                     reverse=True)
        self.assertEqual(ids, ['abc-7.3.0-40.fc44.aurora.aarch64', 'abc-7.3.0-39.fc44.aurora.aarch64',
                               'abc-7.3.0-26.fc44.aurora.aarch64', 'abc-7.3.0-neo.test1', 'abc-7.3.0-neo.final'])
        newest = subprocess.check_output(['sort', '-V'], input='\n'.join(versions), text=True).split()[-1]
        self.assertEqual(newest, '7.3.0-neo.test1')

    def test_entry_ids_compare_name_then_version_then_release(self):
        order = functools.cmp_to_key(bootchain.grub_entry_cmp)
        self.assertGreater(order('abc-7.3.0-aurora-tb3c'), order('abc-7.3.0-aurora-fleet37'))
        self.assertGreater(order('abc-7.3'), order('abc-7.1'))
        self.assertGreater(order('7.3'), order('7.1'))
        self.assertEqual(bootchain.grub_entry_cmp('abc-7.3', 'abc-7.3'), 0)

    def test_process_start_reads_a_live_process(self):
        update = bootchain.Update(Path('/'), {})
        start = update.process_start(os.getpid())
        self.assertRegex(start, r'^[0-9]+$')
        self.assertEqual(update.process_start(os.getpid()), start)
        self.assertIsNone(update.process_start('not a pid'))


@unittest.skipUnless(shutil.which('dtc') and shutil.which('fdtget'), 'requires dtc')
class KernelTransactionTests(unittest.TestCase):
    """Reinstalls, removals and upgrades, with kernel-install's phases in dnf's order."""
    setUp = BootchainTests.setUp
    put = BootchainTests.put
    dtb = BootchainTests.dtb
    kernel = BootchainTests.kernel

    MACHINE = '0123456789abcdef0123456789abcdef'
    OLDER = '7.3.0-39.fc44.aurora.aarch64'
    DEFAULT = '7.3.0-40.fc44.aurora.aarch64'
    NEW = '7.3.0-41.fc44.aurora.aarch64'
    LOCAL = '7.3.0-neo.test1'  # A hand-installed kernel: sort -V puts it above every release.

    def boot_setup(self, default=DEFAULT):
        self.env.update(ESP_ROOT='/esp', ESP_DEVICE='/dev/test-esp', ESP_FSTYPE='vfat')
        self.put('/proc/device-tree/compatible', b'apple,j413\0apple,t8112\0')
        self.put('/proc/device-tree/chosen/asahi,m1n1-stage1-version', b'1.0.0b4\0')
        self.put('/etc/machine-id', f'{self.MACHINE}\n'.encode())
        self.addCleanup(patch.stopall)
        patch.object(bootchain.Update, 'check_esp').start()
        patch.object(bootchain.Update, 'flush_esp').start()
        self.marker = self.root / 'esp/aura-try'
        self.candidate = self.target.with_name('boot.bin.next')
        self.receipt = self.target.with_name('boot.bin.next.json')
        self.attempts = self.root / 'var/lib/aurora-stage2/attempts'
        self.record = self.root / 'run/update-m1n1/transaction'
        self.trees = {}
        for cells, version in enumerate((self.OLDER, self.DEFAULT, self.LOCAL), start=2):
            self.install(version, cells)
            self.entry(version)
        self.set_default(default)
        # The default kernel's Stage 2 is live, as after its committed trial.
        self.target.write_bytes(self.update().plan()[3])
        self.update().apply()
        self.live = self.target.read_bytes()
        self.assertEqual(os.readlink(self.link), f'dtb-{default}')
        self.assert_no_trial()

    def install(self, version, cells):
        self.trees[version] = self.kernel(version, cells).read_bytes()

    def erase(self, version):
        shutil.rmtree(self.root / f'usr/lib/modules/{version}')

    def entry_id(self, version):
        return f'{self.MACHINE}-{version}'

    def entry(self, version):
        self.put(f'/boot/loader/entries/{self.entry_id(version)}.conf',
                 f'title Aurora ({version})\nversion {version}\nlinux /vmlinuz-{version}\n'.encode())

    def set_default(self, version):
        self.put('/boot/grub2/grubenv', f'# GRUB Environment Block\nsaved_entry={self.entry_id(version)}\n'.encode())

    def update(self, action='refresh', version='', **env):
        settings = dict(self.env, **env)
        if action != 'refresh':
            settings.update(AURORA_KERNEL_ACTION=action, AURORA_KERNEL_VERSION=version)
        return bootchain.Update(self.root, settings)

    def kernel_install(self, command, version):
        """One kernel-install call: this hook, then GRUB's plugins (UPDATEDEFAULT=yes)."""
        update = self.update(command, version)
        if command == 'remove':
            if not update.defer_remove():
                update.apply()
            (self.root / f'boot/loader/entries/{self.entry_id(version)}.conf').unlink()
            shutil.rmtree(self.root / f'boot/dtb-{version}', ignore_errors=True)
        else:
            update.apply()
            self.entry(version)
            self.set_default(version)

    def begin(self, start=b'987654'):
        """The transaction's pre-transaction file trigger; dnf5 runs as pid 4242."""
        self.put('/proc/4242/stat', b'4242 (dnf5) S 1 4242 4242 0 -1 4194560 0 0 0 0 0 0 0 0 20 0 1 0 '
                 + start + b' 0 0\n')
        self.update(AURORA_RPM_TRANSACTION_PID='4242').begin_transaction()
        self.assertTrue(self.record.exists())

    def end(self):
        """The transaction's closing file triggers."""
        if self.update().end_transaction():
            self.update().apply()
        self.assertFalse(self.record.exists())
        self.assertFalse(self.update().end_transaction())

    def assert_no_trial(self):
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.candidate.exists())
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.target.read_bytes(), self.live)

    def assert_trial_for(self, version):
        """Armed for this kernel with its own trees and no other kernel's; the live image kept."""
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')
        self.assertEqual(json.loads(self.receipt.read_text())['kernel'], version)
        candidate = self.candidate.read_bytes()
        for other, tree in self.trees.items():
            (self.assertIn if other == version else self.assertNotIn)(tree, candidate)
        self.assertEqual(os.readlink(self.link), f'dtb-{version}')
        self.assertEqual(self.target.read_bytes(), self.live)

    def test_reinstall_of_the_default_kernel_arms_nothing(self):
        self.boot_setup()
        self.begin()
        # dnf has put the new instance's files in place; the old instance's
        # %preun removes the kernel, then the new one's %posttrans adds it.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.kernel_install('remove', self.DEFAULT)
        self.assertIn(f'kernel {self.DEFAULT} removed inside a package transaction', out.getvalue())
        self.assert_no_trial()
        self.assertFalse(self.link.is_symlink())
        self.kernel_install('add', self.DEFAULT)
        self.end()
        self.assert_no_trial()
        self.assertEqual(os.readlink(self.link), f'dtb-{self.DEFAULT}')
        self.assertFalse(self.attempts.exists())

    def test_reinstall_without_a_transaction_record_withdraws_the_wrong_trial(self):
        # As in the transaction that installs this updater: no record, so the
        # removal acts at once, on GRUB's next entry rather than the local kernel.
        self.boot_setup()
        self.kernel_install('remove', self.DEFAULT)
        self.assert_trial_for(self.OLDER)
        wrong = hashlib.sha256(self.candidate.read_bytes()).hexdigest()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.kernel_install('add', self.DEFAULT)
        self.assertIn(f'Stage 2 trial for kernel {self.OLDER} withdrawn before it was booted', out.getvalue())
        self.assert_no_trial()
        self.assertEqual(os.readlink(self.link), f'dtb-{self.DEFAULT}')
        self.assertFalse((self.attempts / wrong).exists())

    def remove_default_for_good(self):
        self.kernel_install('remove', self.DEFAULT)
        self.erase(self.DEFAULT)

    def test_removing_the_default_in_a_transaction_arms_grubs_next_kernel_after_it(self):
        self.boot_setup()
        self.begin()
        self.remove_default_for_good()
        self.assert_no_trial()
        self.end()
        # GRUB boots its first entry when saved_entry names a removed one.
        self.assert_trial_for(self.OLDER)

    def test_removing_the_default_outside_a_transaction_arms_grubs_next_kernel(self):
        self.boot_setup()
        self.remove_default_for_good()
        self.assert_trial_for(self.OLDER)

    def check_non_default_removal(self, transaction):
        self.boot_setup()
        if transaction:
            self.begin()
        self.kernel_install('remove', self.OLDER)
        self.erase(self.OLDER)
        if transaction:
            self.end()
        self.assert_no_trial()
        self.assertEqual(os.readlink(self.link), f'dtb-{self.DEFAULT}')

    def test_removing_a_non_default_kernel_in_a_transaction_changes_nothing(self):
        self.check_non_default_removal(True)

    def test_removing_a_non_default_kernel_outside_a_transaction_changes_nothing(self):
        self.check_non_default_removal(False)

    def test_fresh_install_arms_the_new_kernel(self):
        self.boot_setup()
        # A transaction that only installs kernels records none; its end refreshes nothing.
        self.install(self.NEW, 9)
        self.kernel_install('add', self.NEW)
        self.end()
        self.assert_trial_for(self.NEW)

    def test_upgrade_that_prunes_an_old_kernel_arms_the_new_one_once(self):
        self.boot_setup()
        self.begin()
        self.install(self.NEW, 9)
        self.kernel_install('remove', self.OLDER)
        self.erase(self.OLDER)
        self.kernel_install('add', self.NEW)
        armed = self.candidate.read_bytes()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.end()
        self.assertIn(f'Stage 2 trial for kernel {self.NEW} already armed', out.getvalue())
        self.assert_trial_for(self.NEW)
        self.assertEqual(self.candidate.read_bytes(), armed)
        self.assertEqual([p.name for p in self.attempts.iterdir()], [hashlib.sha256(armed).hexdigest()])

    def check_upgrade_that_prunes_the_default(self, transaction):
        self.boot_setup(default=self.OLDER)
        if transaction:
            self.begin()
        self.install(self.NEW, 9)
        self.kernel_install('remove', self.OLDER)
        self.erase(self.OLDER)
        self.kernel_install('add', self.NEW)
        if transaction:
            self.end()
        self.assert_trial_for(self.NEW)
        self.assertEqual(len(list(self.attempts.iterdir())), 1)

    def test_upgrade_that_prunes_the_default_in_a_transaction(self):
        self.check_upgrade_that_prunes_the_default(True)

    def test_upgrade_that_prunes_the_default_outside_a_transaction_replaces_the_removals_trial(self):
        # The removal arms GRUB's next entry; the add withdraws it for the new
        # kernel instead of refusing because a trial is armed.
        self.check_upgrade_that_prunes_the_default(False)

    def test_a_withdrawn_candidate_may_be_armed_again(self):
        self.boot_setup()
        self.kernel_install('remove', self.DEFAULT)
        first = self.candidate.read_bytes()
        self.kernel_install('add', self.DEFAULT)
        self.assert_no_trial()
        self.remove_default_for_good()
        self.assert_trial_for(self.OLDER)
        self.assertEqual(self.candidate.read_bytes(), first)

    def test_a_trial_that_fell_back_is_still_never_rearmed(self):
        self.boot_setup()
        self.remove_default_for_good()
        self.assert_trial_for(self.OLDER)
        self.marker.write_bytes(b'spent\nm1n1/boot.bin.next\n')  # Stage 1 tried it and fell back.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.update().apply()
        self.assertIn('already attempted', out.getvalue())
        self.assertEqual(self.marker.read_bytes(), b'spent\nm1n1/boot.bin.next\n')
        self.assertEqual(self.target.read_bytes(), self.live)

    def test_a_record_of_a_finished_transaction_is_ignored(self):
        self.boot_setup()
        for change in ('exited', 'pid reused'):
            with self.subTest(change=change):
                self.begin()
                if change == 'exited':
                    (self.root / 'proc/4242/stat').unlink()
                else:
                    self.put('/proc/4242/stat', b'4242 (bash) S 1 4242 4242 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 '
                             b'111 0 0\n')
                self.assertFalse(self.update('remove', self.DEFAULT).defer_remove())
                self.assertFalse(self.record.exists())

    def leave_record_of_a_downgrade(self):
        # Erasing this updater runs its pre-transaction trigger but not its
        # closing ones, so the record outlives the dnf process that wrote it.
        self.begin()
        (self.root / 'proc/4242/stat').unlink()
        self.assertEqual(json.loads(self.record.read_text())['deferred'], [])

    def test_a_record_left_by_a_downgrade_never_defers_a_later_kernel_install(self):
        self.boot_setup()
        self.leave_record_of_a_downgrade()
        self.install(self.NEW, 9)
        self.kernel_install('add', self.NEW)  # By hand: as a fresh install.
        self.assert_trial_for(self.NEW)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.kernel_install('remove', self.NEW)  # By hand: acts at once.
        self.assertNotIn('removed inside a package transaction', out.getvalue())
        self.assertFalse(self.record.exists())
        # GRUB's first entry is the previous default again, whose Stage 2 is live.
        self.assert_no_trial()
        self.assertEqual(os.readlink(self.link), f'dtb-{self.DEFAULT}')

    def test_a_record_left_by_a_downgrade_is_cleared_without_a_refresh(self):
        self.boot_setup()
        self.leave_record_of_a_downgrade()
        # The closing trigger of the updater installed again.
        self.assertFalse(self.update().end_transaction())
        self.assertFalse(self.record.exists())

    def test_without_a_transaction_process_nothing_is_recorded(self):
        self.boot_setup()
        for pid in ('', '1', '4242', 'x'):
            with self.subTest(pid=pid):
                self.update(AURORA_RPM_TRANSACTION_PID=pid).begin_transaction()
                self.assertFalse(self.record.exists())

    def test_an_armed_trial_this_updater_did_not_arm_is_left_alone(self):
        self.boot_setup()
        self.candidate.write_bytes(b'armed by hand')
        self.marker.write_bytes(b'armed\nm1n1/boot.bin.next\n')
        self.update().apply()
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')
        self.assertEqual(self.candidate.read_bytes(), b'armed by hand')

    def test_numeric_and_title_defaults_follow_grubs_menu(self):
        self.boot_setup()
        update = self.update()
        images = update.kernel_images()
        menu = update.boot_menu(images)
        self.assertEqual([version for _, version, _ in menu], [self.DEFAULT, self.OLDER, self.LOCAL])
        for saved, expected in (('1', self.OLDER), ('2', self.LOCAL), ('3', None),
                                (f'Aurora ({self.LOCAL})', self.LOCAL)):
            with self.subTest(saved=saved):
                self.put('/boot/grub2/grubenv', f'saved_entry={saved}\n'.encode())
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(update.default_kernel(images, menu), expected)

    def test_the_added_kernels_entry_counts_before_kernel_install_writes_it(self):
        self.boot_setup()
        self.install(self.NEW, 9)
        update = self.update('add', self.NEW)
        menu = update.boot_menu(update.kernel_images())
        self.assertEqual(menu[0], (self.entry_id(self.NEW), self.NEW, ''))


if __name__ == '__main__':
    unittest.main()
