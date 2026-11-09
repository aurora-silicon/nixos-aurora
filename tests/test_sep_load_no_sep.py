"""load-driver gives up at once on a Mac whose kernel enabled no SEP.

Without an apple_sep platform profile for the SoC or board the module loads,
logs "no platform profile for this SoC; the SEP stays disabled" and creates no
*.sep device. No trusted key can be sealed then, and waiting the whole ready
timeout only held the boot (aurora-sep.service, 120 s on a J614c).
"""

import os
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOAD_DRIVER = ROOT / 'sep/load-driver'


class NoSepTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self.tmpdir.name)
        self.sysfs = tmp / 'devices'
        self.sysfs.mkdir()
        # modprobe succeeds and keyctl never gets a sealed key back, as on
        # the J614c, where the module loads but probes nothing.
        bin_dir = tmp / 'bin'
        bin_dir.mkdir()
        # Its scratch folder is in /run, which only root may write; the test
        # runs unprivileged, so give it one in the test's own folder.
        scratch = shlex.quote(f'{tmp}/aurora-sep-load.XXXXXX')
        stubs = {'modprobe': 'exit 0', 'keyctl': 'exit 1',
                 'mktemp': f'exec {shlex.quote(shutil.which("mktemp"))} -d {scratch}'}
        for name, body in stubs.items():
            stub = bin_dir / name
            stub.write_text(f'#!/bin/sh\n{body}\n')
            stub.chmod(0o755)
        self.env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}',
                        AURORA_SEP_SESSION='1', AURORA_SEP_SYSFS=str(self.sysfs),
                        AURORA_SEP_READY_TIMEOUT='20')

    def tearDown(self):
        self.tmpdir.cleanup()

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

    def test_a_sep_device_is_still_waited_for(self):
        (self.sysfs / '2c3800000.sep').mkdir()
        self.env['AURORA_SEP_READY_TIMEOUT'] = '1'
        done, took = self.run_load_driver()
        self.assertEqual(done.returncode, 1)
        self.assertNotIn('enabled no SEP', done.stderr)
        self.assertIn('did not seal and unseal', done.stderr)

    def test_a_keybag_the_driver_gave_up_on_stops_the_wait(self):
        # An unfinished create the driver can't clear: no key seals this boot.
        diag = self.sysfs / '2c3800000.sep' / 'diag'
        diag.mkdir(parents=True)
        (diag / 'keybag').write_text('failed\n')
        done, took = self.run_load_driver()
        self.assertEqual(done.returncode, 1)
        self.assertLess(took, 5)
        self.assertIn("run 'aurora-xart status'", done.stderr)
        self.assertNotIn('did not seal and unseal', done.stderr)

    def test_a_keybag_still_being_created_is_waited_for(self):
        diag = self.sysfs / '2c3800000.sep' / 'diag'
        diag.mkdir(parents=True)
        (diag / 'keybag').write_text('unknown\n')
        self.env['AURORA_SEP_READY_TIMEOUT'] = '1'
        done, _ = self.run_load_driver()
        self.assertEqual(done.returncode, 1)
        self.assertIn('did not seal and unseal', done.stderr)


if __name__ == '__main__':
    unittest.main()
