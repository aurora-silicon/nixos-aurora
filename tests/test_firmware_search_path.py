"""Exercise the activation helper against private files, never host sysfs."""
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'firmware/restore-search-path.sh'


class FirmwareSearchPathTests(unittest.TestCase):
    def test_each_activation_restores_the_per_device_tree_without_changing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parameter = root / 'parameter'
            vendor = root / 'vendorfw'
            vendor.mkdir()
            calibration = vendor / 'calibration'
            calibration.write_bytes(b'per-device fixture')
            for store in ('/nix/store/first-firmware/lib/firmware', '/nix/store/next-firmware/lib/firmware'):
                # NixOS udev activation replaces the path on every switch.
                parameter.write_text(store)
                subprocess.run(['sh', str(SCRIPT), str(parameter), str(vendor)], check=True)
                self.assertEqual(parameter.read_text(), str(vendor))
                self.assertEqual(list(vendor.iterdir()), [calibration])
                self.assertEqual(calibration.read_bytes(), b'per-device fixture')

    def test_before_handoff_the_store_path_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parameter = root / 'parameter'
            parameter.write_text('/nix/store/firmware/lib/firmware')
            subprocess.run(['sh', str(SCRIPT), str(parameter), str(root / 'missing')], check=True)
            self.assertEqual(parameter.read_text(), '/nix/store/firmware/lib/firmware')

    def test_a_missing_kernel_parameter_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vendor = root / 'vendorfw'
            vendor.mkdir()
            parameter = root / 'missing'
            subprocess.run(['sh', str(SCRIPT), str(parameter), str(vendor)], check=True)
            self.assertFalse(parameter.exists())
