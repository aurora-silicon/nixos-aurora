#!/usr/bin/env python3
"""Exercise shared hardware validation with a distro built-in override."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

VALIDATOR = Path(__file__).resolve().parents[1] / "kernel/validate-config.py"


class KernelRequirements(unittest.TestCase):
    def check_requirements(self, resolved):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "shared").write_text("CONFIG_SPI_HID_APPLE_OF=m\nCONFIG_APPLE_SEP=m\n# CONFIG_TRUSTED_KEYS_TPM is not set\n")
            (root / "common").write_text("CONFIG_SPI_HID_APPLE_OF=y\n")
            (root / "resolved").write_text(resolved)
            return subprocess.run([sys.executable, str(VALIDATOR), str(root / "shared"),
                                   str(root / "common"), str(root / "resolved")],
                                  capture_output=True, text=True)

    def test_common_built_in_requirement_overrides_shared_module(self):
        result = self.check_requirements("CONFIG_SPI_HID_APPLE_OF=y\nCONFIG_APPLE_SEP=m\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dropped_shared_driver_is_still_rejected(self):
        result = self.check_requirements("CONFIG_SPI_HID_APPLE_OF=y\n# CONFIG_APPLE_SEP is not set\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CONFIG_APPLE_SEP", result.stderr)


if __name__ == "__main__":
    unittest.main()
