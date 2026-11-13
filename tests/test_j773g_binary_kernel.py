import hashlib
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / "packages" / "j773g-kernel" / "run59"


class J773gBinaryKernelTests(unittest.TestCase):
    def test_payload_hashes(self):
        expected = {
            "Image": "13d3d96630b2cb68c5d3828819431fe5b4c851a4f40c0b498978ead27fe662e7",
            "t8132-j773g.dtb": "5a72db650a379a3320d2736be69a152c5836e16a3cb038a50f0d692180620e46",
            "config": "f21c4062336081cb004fb12eff2bafa9d0bdfecb98c9e4fb63f6db35c363219c",
        }
        for name, digest in expected.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((PAYLOAD / name).read_bytes()).hexdigest(), digest)

    def test_kernel_release_and_boot_drivers(self):
        image = (PAYLOAD / "Image").read_bytes()
        config = (PAYLOAD / "config").read_text()
        self.assertIn(b"Linux version 7.3.0-m4atlrx+ ", image)
        for option in (
            "CONFIG_APPLE_WATCHDOG=y",
            "CONFIG_NVME_APPLE=y",
            "CONFIG_BTRFS_FS=y",
            "CONFIG_EXT4_FS=y",
            "CONFIG_VFAT_FS=y",
        ):
            self.assertIn(option, config)

    def test_profile_is_opt_in(self):
        flake = (ROOT / "flake.nix").read_text()
        generic = flake.split("j773gKernel =", 1)[0]
        self.assertNotIn("j773g", generic)
        self.assertIn('aurora-j773g-kde = makeJ773gSystem "kde";', flake)

    def test_esp_is_label_mounted_and_nonfatal(self):
        module = (ROOT / "modules" / "j773g.nix").read_text()
        self.assertIn('/dev/disk/by-label/AURORA_EFI', module)
        self.assertIn('"nofail"', module)


if __name__ == "__main__":
    unittest.main()
