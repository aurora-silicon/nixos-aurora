import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PeripheralAdmissionTests(unittest.TestCase):
    def test_neo_keyboard_probe_follows_firmware_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compatible = root / "compatible"
            compatible.write_bytes(b"apple,j700\0apple,t8140\0")
            firmware = root / "firmware"
            (firmware / "apple").mkdir(parents=True)
            (firmware / "apple/tpmtfw-j700.bin").write_bytes(b"fixture")
            calls = root / "module-calls"
            modprobe = root / "modprobe"
            modprobe.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "$AURORA_TEST_CALLS"\n')
            modprobe.chmod(0o755)
            env = dict(
                os.environ,
                AURORA_DT_COMPATIBLE=str(compatible),
                AURORA_FIRMWARE_ROOT=str(firmware),
                AURORA_MODPROBE=str(modprobe),
                AURORA_TEST_CALLS=str(calls),
            )
            script = ROOT / "firmware/aurora-peripheral-firmware.sh"
            subprocess.run(["sh", str(script)], check=True, env=env, capture_output=True)
            self.assertEqual(calls.read_text().splitlines(), ["dockchannel-hid"])

            (firmware / "apple/tpmtfw-j700.bin").unlink()
            calls.unlink()
            result = subprocess.run(["sh", str(script)], check=True, env=env, capture_output=True)
            self.assertIn(b"trackpad firmware missing", result.stderr)
            self.assertEqual(calls.read_text().splitlines(), ["dockchannel-hid"])

    def test_every_mac_gets_its_built_in_keyboard(self):
        # dockchannel-hid drives the keyboard and trackpad of every M2-and-later
        # MacBook, not only the Neo; a Mac without the device loads it unused.
        script = ROOT / "firmware/aurora-peripheral-firmware.sh"
        for board in (b"apple,j413\0apple,t8112\0", b"apple,j414s\0apple,t6020\0",
                      b"apple,j274\0apple,t8103\0"):
            with self.subTest(board=board), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                compatible = root / "compatible"
                compatible.write_bytes(board)
                calls = root / "module-calls"
                modprobe = root / "modprobe"
                modprobe.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "$AURORA_TEST_CALLS"\n')
                modprobe.chmod(0o755)
                env = dict(
                    os.environ,
                    AURORA_DT_COMPATIBLE=str(compatible),
                    AURORA_FIRMWARE_ROOT=str(root / "no-firmware"),
                    AURORA_MODPROBE=str(modprobe),
                    AURORA_TEST_CALLS=str(calls),
                )
                result = subprocess.run(["sh", str(script)], check=True, env=env,
                                        capture_output=True)
                self.assertEqual(calls.read_text().splitlines(), ["dockchannel-hid", "aop"])
                self.assertNotIn(b"trackpad firmware missing", result.stderr)

    def test_keyboard_reaches_the_initrd_even_when_extraction_fails(self):
        module = (ROOT / "modules/firmware.nix").read_text()
        initrd = module.split("boot.initrd.availableKernelModules = [", 1)[1].split("]", 1)[0]
        blacklist = module.split("boot.blacklistedKernelModules = [", 1)[1].split("]", 1)[0]
        self.assertIn('"dockchannel-hid"', initrd)
        self.assertIn('"dockchannel-hid"', blacklist)
        loader = module.split('name = "aurora-load-vendor-firmware";', 1)[1]
        extract = loader.index("aurora-extract-vendor-firmware || status=$?")
        admit = loader.index("/bin/aurora-peripheral-admission")
        self.assertLess(extract, admit)
        self.assertIn('exit "$status"', loader[admit:loader.index("\n  };")])
        # The extraction step owns the early exit for boots without an ESP.
        self.assertNotIn("exit 0", loader[:loader.index("\n  };")])
