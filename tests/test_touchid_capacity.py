# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise ENOSPC through the patched driver and fprintd using fake storage."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SEP = ROOT / 'sep'
OVERLAY = (ROOT / 'overlay.nix').read_text()


def overlay_patches(package):
    # The patch list of one override, in the order the build applies it.
    block = re.search(r'^  ' + package + r' = prev\.' + package + r'\.overrideAttrs .*?^  \}\);$',
                      OVERLAY, re.M | re.S)
    if block is None:
        raise AssertionError(f'no {package} override in overlay.nix')
    return block[0], re.findall(r'^\s*\./sep/(\S+\.patch)$', block[0], re.M)


class TouchIdCapacityTests(unittest.TestCase):
    def test_enospc_reports_full_without_collecting_any_sep_print(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            # Only these unchanged upstream functions are needed. Apply the
            # overlay's patch, not a reimplementation of the fixed callback.
            shutil.copytree(ROOT / 'tests/fixtures/fprintd-1.94.5', source, dirs_exist_ok=True)
            subprocess.run(['git', 'apply', str(SEP / '0004-aurora-report-data-full-without-garbage-collection.patch')],
                           cwd=source, check=True)
            # The first patch creates the whole driver. The include filter
            # avoids needing unrelated libfprint files while applying the
            # driver's patch stack in the overlay's order.
            _, patches = overlay_patches('libfprint')
            self.assertEqual(patches[0], 'libfprint-1.94.100-apple-sep.patch')
            self.assertEqual(patches[-1], '0010-aurora-report-fingerprint-storage-full.patch')
            for patch in patches:
                subprocess.run(['git', 'apply', '--include=libfprint/drivers/aurora/aurora.c',
                                str(SEP / patch)], cwd=source, check=True)
            self.assertRegex((source / 'libfprint/drivers/aurora/aurora.c').read_text(),
                             r'(?m)^#define FP_COMPONENT "apple-sep"$')
            subprocess.run(['python3', str(SEP / 'test_enroll_capacity.py'),
                            str(source / 'src/device.c'), '--aurora',
                            str(source / 'libfprint/drivers/aurora/aurora.c'),
                            '--enroll-utils', str(source / 'utils/enroll.c')], check=True)

    def test_data_full_driver_requires_the_guarded_daemon(self):
        block, patches = overlay_patches('fprintd')
        self.assertEqual(patches[-1], '0004-aurora-report-data-full-without-garbage-collection.patch')
        self.assertIn('auroraNoEnrollGc = 1;', block)
        self.assertIn('${stableFile ./sep/test_enroll_capacity.py} src/device.c --enroll-utils utils/enroll.c', block)
        module = (ROOT / 'modules/sep.nix').read_text()
        self.assertIn('assertion = (config.services.fprintd.package.auroraNoEnrollGc or 0) >= 1;', module)


if __name__ == '__main__':
    unittest.main()
