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

    def extract(self, root, esp):
        """Runs the module's extraction script with the ESP mounted at esp."""
        module = (ROOT / "modules/firmware.nix").read_text()
        block = module.split('name = "aurora-extract-vendor-firmware";', 1)[1]
        text = block.split("text = ''\n", 1)[1].split("\n    '';", 1)[0].replace("''${", "${")
        text = text.replace("/sys/firmware/devicetree/base/chosen/asahi,efi-system-partition",
                            str(root / "property")).replace("/run/aurora-firmware", str(root / "destination"))
        (root / "property").write_bytes(b"5A1E0001-0000-4000-8000-00000000E5B0\0")
        tools = root / "bin"
        tools.mkdir()
        for name, body in (("udevadm", "exit 0"), ("findmnt", f'echo "{esp}"'),
                           ("mount", 'echo "mount $*" >> "$AURORA_TEST_CALLS"; exit 32'),
                           ("cpio", 'echo "cpio $*" >> "$AURORA_TEST_CALLS"; mkdir -p vendorfw; '
                                    "cat > vendorfw/.vendorfw.manifest")):
            (tools / name).write_text(f"#!/bin/sh\n{body}\n")
            (tools / name).chmod(0o755)
        calls = root / "calls"
        calls.touch()
        env = dict(os.environ, PATH=f'{tools}:{os.environ["PATH"]}', AURORA_TEST_CALLS=str(calls))
        result = subprocess.run(["bash", "-euo", "pipefail", "-c", text], env=env, capture_output=True)
        return result, calls.read_text().splitlines()

    def test_runtime_retry_reads_the_mounted_esp(self):
        # The installed system has the ESP mounted read-write at /boot, and a
        # second, read-only mount is refused, so the retry reads it in place.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "esp/vendorfw").mkdir(parents=True)
            (root / "esp/vendorfw/firmware.cpio").write_bytes(b"fixture")
            result, calls = self.extract(root, root / "esp")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls, ["cpio --quiet --extract --unconditional --no-absolute-filenames"])
            self.assertEqual((root / "destination/vendorfw/.vendorfw.manifest").read_bytes(), b"fixture")

    def test_esp_without_vendor_firmware_is_not_a_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "esp").mkdir()
            result, calls = self.extract(root, root / "esp")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b"the ESP has no vendor firmware; admitting peripherals without it", result.stderr)
            self.assertEqual(calls, [])

    def test_initrd_leaves_the_result_to_the_installed_system(self):
        module = (ROOT / "modules/firmware.nix").read_text()
        loader = module.split('name = "aurora-load-vendor-firmware";', 1)[1]
        loader = loader[:loader.index("\n  };")]
        defer = loader.index('"$status" != 0 && "\'\'${1:-initrd}" != runtime')
        self.assertLess(loader.index("aurora-extract-vendor-firmware || status=$?"), defer)
        self.assertIn("status=0", loader[defer:loader.index("/bin/aurora-peripheral-admission")])
