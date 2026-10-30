#!/usr/bin/env python3
"""Exercise shared hardware validation with a distro built-in override."""
import hashlib
import json
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



ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ROOT / "kernel/check-required.py"
BASE = ("CONFIG_DM_CRYPT=m\nCONFIG_DM_INTEGRITY=m\nCONFIG_BT=m\nCONFIG_NF_TABLES=m\nCONFIG_EXFAT_FS=m\n"
        "CONFIG_HID_GENERIC=y\nCONFIG_NLS_UTF8=y\nCONFIG_VFAT_FS=y\nCONFIG_FAT_DEFAULT_CODEPAGE=437\n"
        "CONFIG_NLS_CODEPAGE_437=y\n")


def config_values(path):
    result = {}
    for line in path.read_text().splitlines():
        if line.startswith("CONFIG_"):
            key, value = line.split("=", 1)
            result[key] = value
        elif line.startswith("# CONFIG_") and line.endswith(" is not set"):
            result[line.split()[1]] = "n"
    return result


class ImageRequirements(unittest.TestCase):
    def check(self, resolved):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "resolved"
            path.write_text(resolved)
            return subprocess.run([sys.executable, str(REQUIRED), str(path)], capture_output=True, text=True)

    def test_complete_configuration_passes(self):
        result = self.check(BASE + 'CONFIG_FAT_DEFAULT_IOCHARSET="ascii"\nCONFIG_NLS_ASCII=y\n')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_each_required_option_is_checked(self):
        for name in ("DM_CRYPT", "DM_INTEGRITY", "BT", "NF_TABLES", "EXFAT_FS", "HID_GENERIC", "NLS_UTF8"):
            with self.subTest(name=name):
                resolved = BASE.replace(f"CONFIG_{name}=", f"# CONFIG_{name} is not set\n#")
                result = self.check(resolved + 'CONFIG_FAT_DEFAULT_IOCHARSET="ascii"\nCONFIG_NLS_ASCII=y\n')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"CONFIG_{name}", result.stderr)

    def test_fat_default_iocharset_needs_its_nls_table(self):
        result = self.check(BASE + 'CONFIG_FAT_DEFAULT_IOCHARSET="iso8859-1"\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CONFIG_NLS_ISO8859_1", result.stderr)
        result = self.check(BASE + 'CONFIG_FAT_DEFAULT_IOCHARSET="iso8859-1"\nCONFIG_NLS_ISO8859_1=m\n')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fat_default_codepage_needs_its_nls_table(self):
        resolved = BASE.replace("CONFIG_NLS_CODEPAGE_437=y\n", "")
        result = self.check(resolved + 'CONFIG_FAT_DEFAULT_IOCHARSET="ascii"\nCONFIG_NLS_ASCII=y\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CONFIG_NLS_CODEPAGE_437", result.stderr)


class SharedDistributionConfig(unittest.TestCase):
    def test_vendored_files_match_their_recorded_source(self):
        upstream = json.loads((ROOT / "kernel/provenance.json").read_text())["config_upstream"]
        for name, key in (("config", "config_sha256"), ("common.config", "common_config_sha256")):
            digest = hashlib.sha256((ROOT / "kernel" / name).read_bytes()).hexdigest()
            self.assertEqual(digest, upstream[key], name)

    def test_shared_config_meets_the_image_requirements(self):
        result = subprocess.run([sys.executable, str(REQUIRED), str(ROOT / "kernel/config")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_nixos_changes_only_the_release_suffix(self):
        base = config_values(ROOT / "kernel/config")
        nixos = config_values(ROOT / "kernel/nixos.config")
        changed = {name for name, value in nixos.items() if base.get(name, "n") != value}
        self.assertEqual(changed, {"CONFIG_LOCALVERSION"})


if __name__ == "__main__":
    unittest.main()
