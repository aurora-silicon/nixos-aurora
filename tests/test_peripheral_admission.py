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
