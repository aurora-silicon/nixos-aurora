"""The pre-pivot wait for appledrm's card: when it waits and when it does not.

The script runs against a fake sysfs tree and command line, with modprobe and
udevadm replaced by stubs on PATH.
"""
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'modules/aurora-early-kms-wait.sh'
# sha256 of the script after its first line: fedora-aurora, alarm-aurora and
# nixos-aurora carry the same text, and each pins it here.
BODY_SHA256 = '057a7b0d051d27b21ebc647802c199a4d5848a89cc574c89b768cda30b6d65c1'
ALIAS = 'of:Ndisplay-subsystemT(null)Capple,j616s-display-subsystemCapple,display-subsystem'
SHELLS = [s for s in ('sh', 'bash', 'dash') if shutil.which(s)]

MODPROBE = r'''#!/bin/sh
# -c dumps the configuration; -R ALIAS prints the modules whose alias matches.
case "$1" in
    -c) cat "$STUB/modprobe.conf" 2>/dev/null; exit 0 ;;
    -R) echo "$2" >> "$STUB/resolved"
        found=1
        while read -r pattern module; do
            case "$2" in $pattern) echo "$module"; found=0 ;; esac
        done < "$STUB/aliases"
        exit $found ;;
esac
exit 2
'''
UDEVADM = r'''#!/bin/sh
echo "$*" >> "$STUB/udevadm"
exit "$(cat "$STUB/udevadm-rc" 2>/dev/null || echo 0)"
'''


class EarlyKmsWaitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.stub = self.tmp / 'stub'
        self.bin = self.tmp / 'bin'
        self.devices = self.tmp / 'sys/bus/platform/devices'
        for d in (self.stub, self.bin, self.devices):
            d.mkdir(parents=True)
        for name, text in (('modprobe', MODPROBE), ('udevadm', UDEVADM)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        (self.stub / 'aliases').write_text('of:N*T*Capple,display-subsystem appledrm\n'
                                           'of:N*T*Capple,display-subsystemC* appledrm\n')
        (self.tmp / 'cmdline').write_text('BOOT_IMAGE=/vmlinuz root=UUID=0 ro quiet\n')
        text = SCRIPT.read_text()
        self.assertTrue(text.endswith('\naurora_early_kms_wait\n'))
        # Everything but the last line, which runs it on the real /sys.
        (self.tmp / 'functions').write_text(text[:-len('aurora_early_kms_wait\n')])

    def device(self, name='display-subsystem', alias=ALIAS, driver=False):
        dev = self.devices / name
        dev.mkdir()
        if alias is not None:
            (dev / 'modalias').write_text(alias + '\n')
        if driver:
            (dev / 'driver').mkdir()
        return dev

    def run_wait(self, shell):
        for name in ('udevadm', 'resolved'):
            (self.stub / name).unlink(missing_ok=True)
        env = {'PATH': f'{self.bin}:{os.environ["PATH"]}', 'STUB': str(self.stub)}
        run = subprocess.run(
            [shell, '-c', '. "$1"; aurora_early_kms_wait "$2" "$3"', 'wait',
             str(self.tmp / 'functions'), str(self.tmp / 'sys'), str(self.tmp / 'cmdline')],
            env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual((run.returncode, run.stdout, run.stderr), (0, '', ''))
        log = self.stub / 'udevadm'
        return log.read_text().splitlines() if log.exists() else []

    def assert_waits(self, name='display-subsystem'):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                self.assertEqual(self.run_wait(shell),
                                 [f'wait --timeout=2 /dev/dri/by-path/platform-{name}-card'])

    def assert_no_wait(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                self.assertEqual(self.run_wait(shell), [])

    def test_the_text_is_the_one_all_three_distributions_carry(self):
        body = SCRIPT.read_bytes().split(b'\n', 1)[1]
        self.assertEqual(hashlib.sha256(body).hexdigest(), BODY_SHA256)
        for shell in SHELLS:
            subprocess.run([shell, '-n', str(SCRIPT)], check=True)
        text = SCRIPT.read_text()
        self.assertNotIn('sleep', text)
        self.assertNotRegex(text, r'(?m)^\s*(set -[eu]|exit)\b')

    def test_no_wait_without_a_display_subsystem(self):
        (self.devices / 'soc:dcp').mkdir()
        self.assert_no_wait()
        self.assertFalse((self.stub / 'resolved').exists())

    def test_waits_when_a_driver_is_bound(self):
        self.device(driver=True)
        self.assert_waits()
        # A bound driver needs no lookup.
        self.assertFalse((self.stub / 'resolved').exists())

    def test_waits_under_the_soc_prefixed_name(self):
        self.device('soc:display-subsystem', driver=True)
        self.assert_waits('soc:display-subsystem')

    def test_waits_when_no_driver_is_bound_yet_but_one_can_bind(self):
        # appledrm still loading from the coldplug, or its probe deferred.
        self.device()
        self.assert_waits()
        self.assertEqual((self.stub / 'resolved').read_text().split(), [ALIAS])

    def test_waits_under_the_soc_prefixed_name_before_the_bind(self):
        self.device('soc:display-subsystem',
                    alias='of:Ndisplay-subsystemT(null)Capple,display-subsystem')
        self.assert_waits('soc:display-subsystem')

    def test_no_wait_when_no_module_matches_the_modalias(self):
        self.device()
        (self.stub / 'aliases').write_text('of:N*T*Capple,dcp apple_dcp\n')
        self.assert_no_wait()
        (self.stub / 'aliases').write_text('')
        self.assert_no_wait()

    def test_no_wait_without_a_modalias(self):
        self.device(alias=None)
        self.assert_no_wait()

    def test_no_wait_when_modprobe_is_missing(self):
        self.device()
        (self.bin / 'modprobe').write_text('#!/bin/sh\nexit 127\n')
        self.assert_no_wait()

    def test_no_wait_when_the_driver_is_blacklisted_in_modprobe_d(self):
        self.device()
        (self.stub / 'modprobe.conf').write_text(
            'blacklist nouveau\nblacklist appledrm\nalias foo bar\noptions appledrm x=1\n')
        self.assert_no_wait()

    def test_no_wait_when_the_driver_is_blacklisted_on_the_command_line(self):
        self.device()
        for arg in ('modprobe.blacklist=appledrm', 'rd.driver.blacklist=appledrm',
                    'module_blacklist=appledrm', 'module_blacklist=nouveau,appledrm,ane',
                    'quiet module_blacklist=nouveau rd.driver.blacklist=appledrm'):
            with self.subTest(arg=arg):
                (self.tmp / 'cmdline').write_text(f'root=UUID=0 {arg} ro\n')
                self.assert_no_wait()

    def test_a_blacklist_names_modules_with_either_dash_or_underscore(self):
        self.device()
        (self.stub / 'aliases').write_text('of:N*T*Capple,display-subsystem* apple-drm_kms\n')
        self.assert_waits()
        for arg in ('module_blacklist=apple_drm-kms', 'modprobe.blacklist=x,apple-drm-kms'):
            with self.subTest(arg=arg):
                (self.tmp / 'cmdline').write_text(f'{arg}\n')
                self.assert_no_wait()

    def test_another_modules_blacklist_does_not_stop_the_wait(self):
        self.device()
        (self.stub / 'modprobe.conf').write_text('blacklist appledrm_old\n# blacklist appledrm\n')
        for line in ('module_blacklist=ane,nouveau', 'modprobe.blacklist=xappledrm,appledrmx',
                     'appledrm=off blacklist=appledrm', 'root=* module_blacklist=*', ''):
            with self.subTest(line=line):
                (self.tmp / 'cmdline').write_text(line + '\n')
                self.assert_waits()
        (self.tmp / 'cmdline').unlink()
        self.assert_waits()

    def test_waits_when_one_of_two_matching_modules_may_load(self):
        self.device()
        (self.stub / 'aliases').write_text('of:N*Capple,display-subsystem* appledrm\n'
                                           'of:N*Capple,display-subsystem* appledrm_ng\n')
        (self.tmp / 'cmdline').write_text('module_blacklist=appledrm\n')
        self.assert_waits()
        (self.tmp / 'cmdline').write_text('module_blacklist=appledrm,appledrm-ng\n')
        self.assert_no_wait()

    def test_a_wait_that_times_out_does_not_fail_the_boot(self):
        self.device(driver=True)
        (self.stub / 'udevadm-rc').write_text('1\n')
        self.assert_waits()


if __name__ == '__main__':
    unittest.main()
