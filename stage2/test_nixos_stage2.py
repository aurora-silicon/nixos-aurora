"""Transactions of the NixOS Stage 2 trial, mirroring fedora-aurora's.

Every ESP, profile and device-tree file is real, under a temporary root;
only the block-device check, the ESP flush and the boot-time mount queries
are replaced, as in test_bootchain.py.
"""
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    'nixos_stage2', Path(os.environ.get('NIXOS_STAGE2_MODULE', HERE / 'nixos_stage2.py')))
nixos_stage2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nixos_stage2)
bootchain = nixos_stage2.bootchain
Refused = nixos_stage2.Refused


def dtb(board, chip='t8112', cells=1):
    dts = f'''/dts-v1/; / {{ compatible = "apple,{board}", "apple,{chip}";
              dart {{ compatible = "apple,t8110-dart"; #iommu-cells = <{cells}>; }}; }};'''
    return subprocess.check_output(['dtc', '-q', '-I', 'dts', '-O', 'dtb'], input=dts.encode())


def image(*blobs, aura=b'AURA'):
    return aura + b''.join(blobs) + gzip.compress(b'U-BOOT', mtime=0)


@unittest.skipUnless(shutil.which('dtc') and shutil.which('fdtget'), 'requires dtc')
class NixosTrialTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.addCleanup(patch.stopall)
        patch.object(nixos_stage2.NixosUpdate, 'check_esp').start()
        self.flush = patch.object(nixos_stage2.NixosUpdate, 'flush_esp').start()
        self.env = {
            'AURORA_STAGE2_DIR': '/stage2', 'AURORA_STAGE2_SOURCE': '/stage2/boot.bin',
            'M1N1': '/stage2/aura.bin', 'AURORA_MONITOR_FREE_MARKER': '/stage2/monitor-free',
            'TARGET': '/esp/m1n1/boot.bin', 'ESP_ROOT': '/esp', 'ESP_DEVICE': '/dev/test-esp',
            'ESP_FSTYPE': 'vfat', 'AURORA_SYSTEM_PROFILES': '/nix/var/nix/profiles',
        }
        self.put('/stage2/aura.bin', b'AURA')
        self.target = self.put('/esp/m1n1/boot.bin', b'GOOD-STAGE2')
        self.backup = self.put('/esp/m1n1/boot.bin.old', b'OLDER-STAGE2')
        self.candidate = self.target.with_name('boot.bin.next')
        self.prev = self.target.with_name('boot.bin.prev')
        self.marker = self.root / 'esp/aura-try'
        self.attempts = self.root / 'var/lib/aurora-stage2/attempts'
        self.put('/proc/device-tree/compatible', b'apple,j413\0apple,t8112\0')
        self.put('/proc/device-tree/chosen/asahi,m1n1-stage1-version', b'1.0.0b4\0')
        self.payload = self.stage2(image(dtb('j413', cells=5)))
        self.generation(1, 'kernel-7.3', abi=1)

    def put(self, path, content):
        path = self.root / path.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def stage2(self, payload, abi=1):
        self.put('/stage2/boot.bin', payload)
        self.env['AURORA_STAGE2_SHA256'] = hashlib.sha256(payload).hexdigest()
        if abi is None:
            (self.root / 'stage2/dtb-abi').unlink(missing_ok=True)
        else:
            self.put('/stage2/dtb-abi', f'{abi}\n'.encode())
        return payload

    def generation(self, number, kernel, abi=None, profile='system', specialisations=()):
        """A system profile link to a toplevel, as nixos-rebuild leaves it."""
        toplevel = self.root / f'nix/store/{profile}-{number}-toplevel'
        toplevel.mkdir(parents=True)
        (toplevel / 'nixos-version').write_text('26.05\n')
        image = self.root / f'nix/store/{kernel}/Image'
        image.parent.mkdir(parents=True, exist_ok=True)
        image.touch()
        (toplevel / 'kernel').symlink_to(image)
        if abi is not None:
            (toplevel / 'aurora-dtb-abi').write_text(f'{abi}\n')
        for name, special_kernel, special_abi in specialisations:
            special = self.root / f'nix/store/{profile}-{number}-{name}'
            special.mkdir()
            (special / 'nixos-version').write_text('26.05\n')
            other = self.root / f'nix/store/{special_kernel}/Image'
            other.parent.mkdir(parents=True, exist_ok=True)
            other.touch()
            (special / 'kernel').symlink_to(other)
            if special_abi is not None:
                (special / 'aurora-dtb-abi').write_text(f'{special_abi}\n')
            (toplevel / 'specialisation').mkdir(exist_ok=True)
            (toplevel / 'specialisation' / name).symlink_to(special)
        base = self.root / 'nix/var/nix/profiles'
        if profile != 'system':
            base = base / 'system-profiles'
        base.mkdir(parents=True, exist_ok=True)
        (base / f'{profile}-{number}-link').symlink_to(toplevel)
        current = base / profile
        current.unlink(missing_ok=True)
        current.symlink_to(f'{profile}-{number}-link')
        return toplevel

    def update(self):
        return nixos_stage2.NixosUpdate(self.root, self.env)

    def install(self):
        self.update().install()

    def commit(self):
        self.update().commit()

    def trial_boot(self, relative='m1n1/boot.bin.next'):
        self.marker.write_bytes(f'spent\n{relative}\n'.encode())
        self.put('/proc/device-tree/chosen/aurora,trial', relative.encode() + b'\0')

    def sane(self):
        self.put('/sys/kernel/debug/devices_deferred', b'')
        original = bootchain.subprocess.check_output

        def output(command, **kwargs):
            if command[0] == 'findmnt':
                return '/dev/mapper/root\n'
            if command[0] == 'lsblk':
                return 'dm-0\nnvme0n1p5\nnvme0n1\n'
            return original(command, **kwargs)
        patch.object(bootchain.subprocess, 'check_output', side_effect=output).start()

    def unchanged(self):
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.backup.read_bytes(), b'OLDER-STAGE2')
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.candidate.exists())

    # Arm, commit, fall back, guard: the transactions fedora-aurora tests.

    def test_install_arms_a_trial_and_keeps_the_live_image(self):
        self.install()
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')
        self.assertEqual(self.candidate.read_bytes(), self.payload)
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.backup.read_bytes(), b'OLDER-STAGE2')
        receipt = json.loads(self.target.with_name('boot.bin.next.json').read_text())
        digest = hashlib.sha256(self.payload).hexdigest()
        self.assertEqual(receipt, {'kernel': digest, 'path': 'm1n1/boot.bin.next', 'sha256': digest,
                                   'dtb_offset': 4, 'generation': 1})
        self.assertEqual(json.loads((self.attempts / digest).read_text()), receipt)
        self.commit()  # The boot that staged it is not a trial boot.
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

    def test_trial_boot_commits_the_candidate(self):
        self.install()
        self.trial_boot()
        self.sane()
        self.commit()
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual(self.prev.read_bytes(), b'GOOD-STAGE2')
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.candidate.exists())
        self.install()  # The same image again is now the live one.
        self.assertFalse(self.marker.exists())

    def test_fallback_keeps_the_live_image_and_never_rearms_that_image(self):
        self.install()
        self.marker.write_bytes(b'spent\nm1n1/boot.bin.next\n')  # Stage 1 fell back.
        with patch('builtins.print') as log:
            self.commit()
        self.assertIn('fell back', log.call_args[0][0])
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.candidate.read_bytes(), self.payload)
        self.install()  # A rebuild with the same image does not retry it.
        self.assertEqual(self.marker.read_bytes(), b'spent\nm1n1/boot.bin.next\n')
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

    def test_a_new_image_after_a_fallback_gets_its_own_trial_and_keeps_the_evidence(self):
        self.install()
        failed = self.candidate.read_bytes()
        self.marker.write_bytes(b'spent\nm1n1/boot.bin.next\n')
        self.stage2(self.payload + b'chosen.bootargs=quiet\n')
        self.install()
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')
        saved = list(self.target.parent.glob('boot.bin.failed-*'))
        self.assertTrue(any(p.read_bytes() == failed for p in saved))

    def test_uncommitted_trial_guard_reboots_to_the_configured_image(self):
        self.install()
        self.trial_boot()
        with patch.object(bootchain.subprocess, 'run') as command:
            self.update().guard()
        command.assert_called_once_with(['systemctl', '--no-block', 'reboot'], check=True)
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

    def test_committed_trial_guard_does_nothing(self):
        self.install()
        self.trial_boot()
        self.sane()
        self.commit()
        with patch.object(bootchain.subprocess, 'run') as command:
            self.update().guard()
        command.assert_not_called()

    def test_failed_dt_checks_refuse_the_commit(self):
        self.install()
        self.trial_boot()
        self.sane()
        self.put('/sys/kernel/debug/devices_deferred', b'dcp\tplatform: waiting for supplier\n')
        dcp = self.root / 'sys/bus/platform/devices/dcp'
        dcp.mkdir(parents=True)
        (dcp / 'of_node').symlink_to(self.root / 'proc/device-tree')
        with self.assertRaisesRegex(Refused, 'DT device still deferred'):
            self.commit()
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertTrue(self.candidate.exists())

    def test_old_stage1_replaces_directly_with_a_backup(self):
        self.put('/proc/device-tree/chosen/asahi,m1n1-stage1-version', b'1.0.0b3\0')
        self.install()
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual(self.backup.read_bytes(), b'GOOD-STAGE2')
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.candidate.exists())

    def test_unchanged_image_writes_nothing(self):
        self.target.write_bytes(self.payload)
        self.install()
        self.assertEqual(self.backup.read_bytes(), b'OLDER-STAGE2')
        self.assertFalse(self.marker.exists())

    def test_digest_mismatch_is_refused(self):
        self.env['AURORA_STAGE2_SHA256'] = '0' * 64
        with self.assertRaisesRegex(Refused, 'does not match its digest'):
            self.install()
        self.unchanged()

    def test_ctxr_slot_is_trialled_and_committed_alone(self):
        self.put('/stage2/monitor-free', b'')
        self.put('/proc/device-tree/compatible', b'apple,j700\0apple,t8140\0')
        ctxr = self.put('/esp/m1n1/boot-ctxr.bin', b'GOOD-CTXR')
        self.env['TARGET'] = '/esp/m1n1/boot-ctxr.bin'
        payload = self.stage2(image(dtb('j700', 't8140')))
        self.install()
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot-ctxr.bin.next\n')
        self.trial_boot('m1n1/boot-ctxr.bin.next')
        self.sane()
        self.env['TARGET'] = '/esp/m1n1/boot.bin'  # The boot service names boot.bin.
        self.commit()
        self.assertEqual(ctxr.read_bytes(), payload)
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(ctxr.with_name('boot-ctxr.bin.prev').read_bytes(), b'GOOD-CTXR')

    # The newest bootloader install decides the trial.

    def test_a_second_install_before_reboot_replaces_the_untried_candidate(self):
        self.install()
        first = hashlib.sha256(self.payload).hexdigest()
        second = self.stage2(self.payload + b'chosen.bootargs=quiet\n')
        self.install()
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')
        self.assertEqual(self.candidate.read_bytes(), second)
        self.assertFalse((self.attempts / first).exists())
        self.assertFalse(list(self.target.parent.glob('boot.bin.failed-*')))
        self.install()  # The same bytes stay armed.
        self.assertEqual(self.candidate.read_bytes(), second)

    def test_rollback_to_the_live_image_withdraws_the_untried_candidate(self):
        self.install()
        self.stage2(b'GOOD-STAGE2')
        self.install()
        self.unchanged()
        self.assertFalse(list(self.attempts.iterdir()))

    def test_a_trial_boot_that_committed_may_arm_the_next_image(self):
        self.install()
        self.trial_boot()
        self.sane()
        self.commit()
        following = self.stage2(self.payload + b'chosen.bootargs=quiet\n')
        self.install()
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')
        self.assertEqual(self.candidate.read_bytes(), following)

    def test_a_committed_trial_boot_arms_again_after_withdrawing_an_image(self):
        self.install()
        committed = self.payload
        self.trial_boot()
        self.sane()
        self.commit()
        self.stage2(committed + b'chosen.bootargs=quiet\n')
        self.install()
        self.stage2(committed)
        self.install()  # Back to the live image: the untried one is withdrawn.
        self.assertFalse(self.marker.exists())
        following = self.stage2(committed + b'chosen.bootargs=splash\n')
        self.install()  # Same trial boot, receipt gone: still an ordinary boot.
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')
        self.assertEqual(self.candidate.read_bytes(), following)
        self.assertEqual(self.target.read_bytes(), committed)

    def test_an_uncommitted_trial_boot_refuses_a_new_image(self):
        self.install()
        self.trial_boot()
        before = self.candidate.read_bytes()
        self.stage2(self.payload + b'chosen.bootargs=quiet\n')
        with self.assertRaisesRegex(Refused, 'trial is running'):
            self.install()
        self.assertEqual(self.candidate.read_bytes(), before)

    def test_another_owners_marker_is_kept(self):
        self.marker.write_bytes(b'armed\nother/image.bin\n')
        with self.assertRaisesRegex(Refused, 'another aura-try'):
            self.install()
        self.assertEqual(self.marker.read_bytes(), b'armed\nother/image.bin\n')

    # The DT ABI generation guard over the generations GRUB lists.

    def test_an_older_listed_generation_refuses_before_any_esp_write(self):
        self.generation(2, 'kernel-7.1', abi=0)
        self.generation(3, 'kernel-7.3', abi=1)
        with self.assertRaises(Refused) as result:
            self.install()
        message = str(result.exception)
        self.assertIn('DT ABI generation 1', message)
        self.assertIn('system-2 (generation 0)', message)
        self.assertNotIn('system-1 ', message)
        self.assertIn('sudo nix-env --profile ' + str(self.root / 'nix/var/nix/profiles/system')
                      + ' --delete-generations 2', message)
        self.assertNotIn('\n', message)
        self.unchanged()
        self.assertFalse(self.attempts.exists())
        self.assertTrue((self.root / 'nix/var/nix/profiles/system-2-link').exists())

    def test_an_undeclared_generation_with_another_kernel_is_generation_one(self):
        self.generation(2, 'kernel-7.2')
        self.install()

    def test_an_undeclared_generation_still_refuses_a_later_generation(self):
        self.stage2(image(dtb('j413', cells=5)), abi=2)
        self.generation(2, 'kernel-7.2')
        self.generation(3, 'kernel-7.3', abi=2)
        with self.assertRaisesRegex(Refused, r'system-2 \(generation 1\)'):
            self.install()
        self.unchanged()

    def test_an_undeclared_generation_with_the_same_kernel_shares_its_generation(self):
        self.generation(2, 'kernel-7.3')
        self.install()
        self.assertTrue(self.marker.exists())

    def test_higher_or_equal_listed_generations_allow_the_change(self):
        self.generation(2, 'kernel-7.4', abi=2)
        self.stage2(self.payload, abi=1)
        self.install()
        self.assertTrue(self.marker.exists())

    def test_generations_beyond_the_grub_limit_are_not_listed(self):
        self.generation(2, 'kernel-7.1', abi=0)
        for number in (3, 4):
            self.generation(number, 'kernel-7.3', abi=1)
        self.env['AURORA_CONFIGURATION_LIMIT'] = '2'
        self.install()
        self.assertTrue(self.marker.exists())
        self.env['AURORA_CONFIGURATION_LIMIT'] = '3'
        with self.assertRaisesRegex(Refused, r'system-2 \(generation 0\)'):
            self.stage2(self.payload + b'chosen.bootargs=quiet\n')
            nixos_stage2.NixosUpdate(self.root, self.env).check_generations()

    def test_specialisations_and_named_profiles_are_listed(self):
        self.generation(2, 'kernel-7.3', abi=1, specialisations=[('old', 'kernel-7.1', 0)])
        with self.assertRaisesRegex(Refused, r'system-2/old \(generation 0\)'):
            self.install()
        shutil.rmtree(self.root / 'nix/store/system-2-toplevel/specialisation')
        self.generation(1, 'kernel-7.0', abi=0, profile='work')
        with self.assertRaisesRegex(Refused, r'work-1 \(generation 0\).*system-profiles/work --delete-generations 1'):
            self.install()
        self.unchanged()

    def test_invalid_declarations_refuse(self):
        self.generation(2, 'kernel-7.3')
        for value in (b'', b'-1\n', b'01\n', b'1 2\n', b'garbage'):
            with self.subTest(value=value):
                (self.root / 'nix/store/system-2-toplevel/aurora-dtb-abi').write_bytes(value)
                with self.assertRaisesRegex(Refused, 'invalid DT ABI generation'):
                    self.install()
                self.unchanged()

    def test_a_generation_added_after_arming_blocks_the_commit(self):
        self.install()
        self.trial_boot()
        self.sane()
        self.generation(2, 'kernel-7.1', abi=0)
        with self.assertRaisesRegex(Refused, 'retained kernels now require an older'):
            self.commit()
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertFalse(self.prev.exists())

    def test_check_skips_an_unchanged_image_and_refuses_a_changed_one(self):
        self.generation(2, 'kernel-7.1', abi=0)
        self.target.write_bytes(self.payload)
        self.update().check()
        self.target.write_bytes(b'GOOD-STAGE2')
        with self.assertRaisesRegex(Refused, r'system-2 \(generation 0\)'):
            self.update().check()

    def test_check_includes_the_configuration_being_installed(self):
        toplevel = self.generation(9, 'kernel-6.9', abi=0, profile='scratch')
        (self.root / 'nix/var/nix/profiles/system-profiles/scratch-9-link').unlink()
        self.env['AURORA_TOPLEVEL'] = str(toplevel.relative_to(self.root))
        with self.assertRaisesRegex(Refused, r'the configuration being installed \(generation 0\)'):
            self.update().check()

    def test_main_reports_a_refusal_and_keeps_the_esp(self):
        self.generation(2, 'kernel-7.1', abi=0)
        env = {key: str(self.root / value.lstrip('/')) if value.startswith('/') else value
               for key, value in self.env.items()}
        env.update(AURORA_STAGE2_LOCK=str(self.root / 'lock'))
        with patch.dict(os.environ, env, clear=True), patch('sys.stderr') as stderr:
            self.assertEqual(nixos_stage2.main(['check']), 1)
        written = ''.join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn('aurora-stage2 check: this Stage 2 uses DT ABI generation 1', written)
        self.assertIn('the boot menu and Stage 2 were left unchanged', written)


class ProvenanceTests(unittest.TestCase):
    def test_bootchain_is_fedora_auroras_unchanged(self):
        provenance = json.loads((HERE / 'provenance.json').read_text())
        for name, digest in provenance['upstream_files_sha256'].items():
            with self.subTest(name):
                self.assertEqual(hashlib.sha256((HERE / name).read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
