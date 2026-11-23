"""When load-driver waits for the enclave and when it stops.

It waits only while diag/keystore says the bring-up is still running
("unknown"), probes trusted keys once after that, and stops at once when
there is nothing to wait for:

- no *.sep device: the kernel enabled no SEP on this Mac (no apple_sep
  platform profile for the SoC or board; aurora-sep.service held the boot
  for 120 s on a J614c before that was handled);
- diag/keystore "closed": the bring-up ended without the key store, which
  is final for the boot;
- a probe that failed after the bring-up ended: the driver's answer does not
  change within the boot, so a retry only held the boot.
"""

import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOAD_DRIVER = ROOT / 'sep/load-driver'

# keyctl that seals and loads keys, as on a Mac whose key store is open.
KEYCTL_WORKS = '''
echo "$*" >>"$KEYCTL_LOG"
case "$1" in
padd) cat >/dev/null; echo 123 ;;
pipe) echo 0123abcd ;;
esac
exit 0
'''

# keyctl that never gets a sealed key back.
KEYCTL_FAILS = '''
echo "$*" >>"$KEYCTL_LOG"
exit 1
'''


class LoadDriverWaitTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self.tmpdir.name)
        self.sysfs = tmp / 'devices'
        self.sysfs.mkdir()
        self.bin_dir = tmp / 'bin'
        self.bin_dir.mkdir()
        self.keyctl_log = tmp / 'keyctl.log'
        self.keyctl_log.write_text('')
        # Its scratch folder is in /run, which only root may write; the test
        # runs unprivileged, so give it one in the test's own folder.
        scratch = shlex.quote(f'{tmp}/aurora-sep-load.XXXXXX')
        self.stub('modprobe', 'exit 0')
        self.stub('mktemp', f'exec {shlex.quote(shutil.which("mktemp"))} -d {scratch}')
        self.stub('keyctl', KEYCTL_FAILS)
        self.env = dict(os.environ, PATH=f'{self.bin_dir}:{os.environ["PATH"]}',
                        AURORA_SEP_SESSION='1', AURORA_SEP_SYSFS=str(self.sysfs),
                        AURORA_SEP_READY_TIMEOUT='20', KEYCTL_LOG=str(self.keyctl_log))

    def tearDown(self):
        self.tmpdir.cleanup()

    def stub(self, name, body):
        path = self.bin_dir / name
        path.write_text(f'#!/bin/sh\n{body}\n')
        path.chmod(0o755)

    def diag(self, **attrs):
        diag = self.sysfs / '2c3800000.sep' / 'diag'
        diag.mkdir(parents=True, exist_ok=True)
        for name, value in attrs.items():
            (diag / name).write_text(f'{value}\n')
        return diag

    def probes(self):
        return [l for l in self.keyctl_log.read_text().splitlines() if l.startswith('padd trusted aurora-sep-check')]

    def run_load_driver(self):
        start = time.monotonic()
        done = subprocess.run(['sh', str(LOAD_DRIVER)], env=self.env, capture_output=True,
                              text=True, check=False, timeout=60)
        return done, time.monotonic() - start

    def test_no_sep_device_returns_at_once(self):
        done, took = self.run_load_driver()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertLess(took, 5)
        self.assertIn('enabled no SEP', done.stderr)
        self.assertEqual(self.probes(), [])

    def test_without_diag_the_probe_runs_once(self):
        # A kernel without diag/keystore waits for the bring-up inside the
        # first trusted-key call; its answer is final.
        (self.sysfs / '2c3800000.sep').mkdir()
        done, took = self.run_load_driver()
        self.assertEqual(done.returncode, 1)
        self.assertLess(took, 5)
        self.assertNotIn('enabled no SEP', done.stderr)
        self.assertIn('did not seal and unseal', done.stderr)
        self.assertEqual(len(self.probes()), 1)

    def test_a_keybag_the_driver_gave_up_on_is_named(self):
        # An unfinished create the driver can't clear: no key seals this boot.
        self.diag(keystore='open', keybag='failed')
        done, took = self.run_load_driver()
        self.assertEqual(done.returncode, 1)
        self.assertLess(took, 5)
        self.assertIn("run 'aurora-xart status'", done.stderr)
        self.assertNotIn('did not seal and unseal', done.stderr)
        self.assertEqual(len(self.probes()), 1)

    def test_a_closed_key_store_stops_at_once_without_a_probe(self):
        self.diag(keystore='closed', keybag='unknown')
        done, took = self.run_load_driver()
        self.assertEqual(done.returncode, 1)
        self.assertLess(took, 5)
        self.assertIn('key store did not open', done.stderr)
        self.assertEqual(self.probes(), [])

    def test_a_failed_probe_after_the_bring_up_is_not_retried(self):
        self.diag(keystore='open', keybag='present')
        done, took = self.run_load_driver()
        self.assertEqual(done.returncode, 1)
        self.assertLess(took, 5)
        self.assertIn('did not seal and unseal a trusted key (key store open, keybag present)',
                      done.stderr)
        self.assertEqual(len(self.probes()), 1)

    def test_a_bring_up_that_never_ends_times_out_without_a_probe(self):
        self.diag(keystore='unknown', keybag='unknown')
        self.env['AURORA_SEP_READY_TIMEOUT'] = '1'
        done, took = self.run_load_driver()
        self.assertEqual(done.returncode, 1)
        self.assertIn('bring-up did not end within 1 s', done.stderr)
        self.assertEqual(self.probes(), [])

    def test_the_probe_waits_for_the_bring_up_to_end(self):
        diag = self.diag(keystore='unknown', keybag='unknown')
        self.stub('keyctl', KEYCTL_WORKS)
        opened = []

        def open_key_store():
            time.sleep(1)
            # Nothing may have probed while the bring-up still ran.
            opened.append(self.probes())
            (diag / 'keystore').write_text('open\n')

        writer = threading.Thread(target=open_key_store)
        writer.start()
        done, took = self.run_load_driver()
        writer.join()
        self.assertEqual(opened, [[]])
        self.assertGreaterEqual(took, 1)
        self.assertIn('trusted keys work after', done.stderr)
        self.assertEqual(len(self.probes()), 1)

    def test_a_timeout_that_is_not_whole_seconds_is_refused(self):
        self.env['AURORA_SEP_READY_TIMEOUT'] = '1.5'
        done, _ = self.run_load_driver()
        self.assertEqual(done.returncode, 2)
        self.assertIn('whole seconds', done.stderr)


if __name__ == '__main__':
    unittest.main()
