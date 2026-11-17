import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RuntimePeripheralTests(unittest.TestCase):
    def admit(self, root, *, ready, firmware=True, aliases=(), bluetooth=True,
              board=b"apple,j614s\0apple,t6040\0", touch_bar=None):
        compatible = root / "compatible"
        compatible.write_bytes(board)
        fw = root / "firmware"
        fw.mkdir()
        if firmware:
            (fw / "brcm").mkdir()
            (fw / "brcm/fixture.bin").write_bytes(b"fixture")
        if touch_bar is not None:
            (fw / "apple").mkdir()
            (fw / f"apple/dfrmtfw-{touch_bar}.bin").write_bytes(b"fixture")
        pci = root / "pci"
        pci.mkdir()
        for index, alias in enumerate(aliases):
            device = pci / str(index)
            device.mkdir()
            (device / "modalias").write_text(alias + "\n")
        calls = root / "calls"
        modprobe = root / "modprobe"
        modprobe.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = --resolve-alias ]; then\n'
            '  case "$2" in\n'
            "    wifi) echo brcmfmac ;;\n"
            "    bluetooth) echo hci_bcm4377 ;;\n"
            "    other) echo unrelated_driver ;;\n"
            "    *) exit 1 ;;\n"
            "  esac\n"
            "else\n"
            '  printf "%s\\n" "$1" >> "$AURORA_TEST_CALLS"\n'
            "fi\n"
        )
        modprobe.chmod(0o755)
        env = dict(
            os.environ,
            AURORA_DT_COMPATIBLE=str(compatible),
            AURORA_FIRMWARE_ROOT=str(fw),
            AURORA_PCI_ROOT=str(pci),
            AURORA_MODPROBE=str(modprobe),
            AURORA_TEST_CALLS=str(calls),
            AURORA_RUNTIME_FIRMWARE_READY=str(int(ready)),
            AURORA_ADMIT_BLUETOOTH=str(int(bluetooth)),
        )
        result = subprocess.run(
            ["sh", str(ROOT / "firmware/aurora-peripheral-firmware.sh")],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return calls.read_text().splitlines()

    def test_initrd_never_probes_runtime_peripherals(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = self.admit(
                Path(temporary), ready=False, aliases=("wifi", "bluetooth")
            )
            self.assertEqual(calls, ["dockchannel-hid", "aop"])

    def test_runtime_uses_the_installed_kernel_aliases(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = self.admit(
                Path(temporary),
                ready=True,
                aliases=("wifi", "bluetooth", "other", "unmatched"),
            )
            self.assertEqual(
                calls, ["dockchannel-hid", "aop", "brcmfmac", "hci_bcm4377", "aop_als"]
            )

    def test_runtime_without_pci_devices_still_admits_uncalibrated_als(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = self.admit(Path(temporary), ready=True)
            self.assertEqual(calls, ["dockchannel-hid", "aop", "aop_als"])

    def test_bluetooth_waits_for_bluetooth_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = self.admit(
                Path(temporary),
                ready=True,
                bluetooth=False,
                aliases=("wifi", "bluetooth"),
            )
            self.assertEqual(calls, ["dockchannel-hid", "aop", "brcmfmac", "aop_als"])

    def test_touch_bar_follows_the_runtime_firmware_path(self):
        # J293: Broadcom radios and the Touch Bar digitizer all read vendorfw
        # while probing, so the runtime pass loads them after path restoration.
        with tempfile.TemporaryDirectory() as temporary:
            calls = self.admit(
                Path(temporary),
                ready=True,
                board=b"apple,j293\0apple,t8103\0",
                touch_bar="j293",
                aliases=("wifi", "bluetooth"),
            )
            self.assertEqual(
                calls,
                ["dockchannel-hid", "aop", "brcmfmac", "hci_bcm4377", "apple_z2", "aop_als"],
            )

    def test_initrd_never_probes_the_touch_bar(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = self.admit(
                Path(temporary),
                ready=False,
                board=b"apple,j493\0apple,t8112\0",
                touch_bar="j493",
                aliases=("wifi", "bluetooth"),
            )
            self.assertEqual(calls, ["dockchannel-hid", "aop"])

    def test_no_vendor_radio_firmware_defers_broadcom(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = self.admit(
                Path(temporary),
                ready=True,
                firmware=False,
                aliases=("wifi", "bluetooth"),
            )
            self.assertEqual(calls, ["dockchannel-hid", "aop", "aop_als"])

    def load(self, root, mode, status):
        tools = root / "bin"
        tools.mkdir()
        calls = root / "calls"
        (root / "system-firmware").mkdir()
        parameter = root / "parameter"
        parameter.write_text("old-path")
        commands = {
            "aurora-extract-vendor-firmware": f"exit {status}",
            "aurora-peripheral-admission": (
                'if [ "$AURORA_RUNTIME_FIRMWARE_READY" = 1 ]; then\n'
                '  test "$(cat "$AURORA_FIRMWARE_PARAMETER")" = "$AURORA_FIRMWARE_ROOT" || exit 99\n'
                "fi\n"
                'echo "$AURORA_RUNTIME_FIRMWARE_READY" > "$AURORA_TEST_CALLS"'
            ),
        }
        for name, body in commands.items():
            path = tools / name
            path.write_text("#!/bin/sh\n" + body + "\n")
            path.chmod(0o755)
        env = dict(
            os.environ,
            PATH=f"{tools}:{os.environ['PATH']}",
            AURORA_TEST_CALLS=str(calls),
            AURORA_FIRMWARE_DESTINATION=str(root / "destination"),
            AURORA_FIRMWARE_FALLBACK=str(root / "fallback"),
            AURORA_SYSTEM_FIRMWARE=str(root / "system-firmware"),
            AURORA_FIRMWARE_PARAMETER=str(parameter),
        )
        result = subprocess.run(
            ["bash", str(ROOT / "firmware/load-vendor-firmware.sh"), mode],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, status, result.stderr)
        return calls.read_text().strip()

    def test_runtime_admission_follows_successful_handoff_and_path_restoration(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(self.load(Path(temporary), "runtime", 0), "1")

    def test_partial_extraction_does_not_admit_new_runtime_devices(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(self.load(Path(temporary), "runtime", 17), "0")

    def test_initrd_success_does_not_admit_runtime_devices(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(self.load(Path(temporary), "initrd", 0), "0")


if __name__ == "__main__":
    unittest.main()
