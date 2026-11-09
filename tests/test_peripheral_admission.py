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

    def extract(self, root, esp, cpio_body=None):
        """Runs the module's extraction script with the ESP mounted at esp."""
        (root / "property").write_bytes(b"5A1E0001-0000-4000-8000-00000000E5B0\0")
        tools = root / "bin"
        tools.mkdir(exist_ok=True)
        cpio_body = cpio_body or ('echo "cpio $*" >> "$AURORA_TEST_CALLS"; mkdir -p vendorfw; '
                                  'cat > vendorfw/.vendorfw.manifest')
        for name, body in (("udevadm", "exit 0"), ("findmnt", f'echo "{esp}"'),
                           ("mount", 'echo "mount $*" >> "$AURORA_TEST_CALLS"; exit 32'),
                           ("cpio", cpio_body)):
            (tools / name).write_text(f"#!/bin/sh\n{body}\n")
            (tools / name).chmod(0o755)
        calls = root / "calls"
        calls.touch()
        env = dict(os.environ, PATH=f'{tools}:{os.environ["PATH"]}', AURORA_TEST_CALLS=str(calls),
                   AURORA_EFI_PROPERTY=str(root / "property"),
                   AURORA_FIRMWARE_DESTINATION=str(root / "destination"),
                   AURORA_PARTUUID_ROOT=str(root / "devices"),
                   AURORA_ESP_MOUNT=str(root / "mount"))
        result = subprocess.run(["bash", str(ROOT / "firmware/extract-vendor-firmware.sh")],
                                env=env, capture_output=True)
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

    def test_partial_extraction_retries_even_after_the_archive_wrote_its_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            esp = root / "esp"
            (esp / "vendorfw").mkdir(parents=True)
            (esp / "vendorfw/firmware.cpio").write_bytes(b"fixture")
            partial = ('echo partial >> "$AURORA_TEST_CALLS"; mkdir -p vendorfw; '
                       'printf manifest > vendorfw/.vendorfw.manifest; exit 17')
            result, calls = self.extract(root, esp, partial)
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertEqual(calls, ["partial"])
            destination = root / "destination"
            self.assertTrue((destination / "vendorfw/.vendorfw.manifest").is_file())
            self.assertFalse((destination / ".vendorfw-extracted").exists())

            result, calls = self.extract(root, esp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(calls), 2)
            self.assertEqual((destination / "vendorfw/.vendorfw.manifest").read_bytes(), b"fixture")
            self.assertTrue((destination / ".vendorfw-extracted").is_file())
            # Once complete, the next runtime invocation does not extract again.
            result, calls = self.extract(root, esp, partial)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(calls), 2)

    def load(self, root, mode, extract_status):
        tools = root / "bin"
        tools.mkdir()
        calls = root / "calls"
        compatible = root / "compatible"
        compatible.write_bytes(b"apple,j413\0apple,t8112\0")
        commands = {
            "aurora-extract-vendor-firmware": f'echo extract >> "$AURORA_TEST_CALLS"; exit {extract_status}',
            "aurora-peripheral-admission":
                'echo "admit:$AURORA_ADMIT_BLUETOOTH:$AURORA_FIRMWARE_ROOT" >> "$AURORA_TEST_CALLS"\n'
                f'exec sh "{ROOT / "firmware/aurora-peripheral-firmware.sh"}"',
            "modprobe": 'echo "module:$1" >> "$AURORA_TEST_CALLS"',
        }
        for name, body in commands.items():
            path = tools / name
            path.write_text(f"#!/bin/sh\n{body}\n")
            path.chmod(0o755)
        (root / "system-firmware").mkdir()
        parameter = root / "parameter"
        parameter.write_text("old-search-path")
        env = dict(os.environ, PATH=f'{tools}:{os.environ["PATH"]}',
                   AURORA_TEST_CALLS=str(calls), AURORA_DT_COMPATIBLE=str(compatible),
                   AURORA_FIRMWARE_DESTINATION=str(root / "destination"),
                   AURORA_FIRMWARE_FALLBACK=str(root / "fallback"),
                   AURORA_SYSTEM_FIRMWARE=str(root / "system-firmware"),
                   AURORA_FIRMWARE_PARAMETER=str(parameter))
        result = subprocess.run(["bash", str(ROOT / "firmware/load-vendor-firmware.sh"), mode],
                                env=env, capture_output=True)
        return result, calls.read_text().splitlines()

    def test_initrd_defers_extraction_failure_but_admits_keyboard(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result, calls = self.load(root, "initrd", 17)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b"the installed system will retry", result.stderr)
            self.assertEqual(calls, ["extract", f"admit:0:{root}/destination/vendorfw",
                                     "module:dockchannel-hid", "module:aop"])
            self.assertEqual((root / "parameter").read_text(), "old-search-path")
            self.assertFalse((root / "fallback").exists())

    def test_runtime_reports_extraction_failure_after_admitting_keyboard(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result, calls = self.load(root, "runtime", 17)
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertEqual(calls, ["extract", f"admit:1:{root}/destination/vendorfw",
                                     "module:dockchannel-hid", "module:aop"])
            self.assertEqual((root / "parameter").read_text(), f"{root}/destination/vendorfw")
            self.assertEqual((root / "fallback").resolve(), root / "system-firmware")

    def test_runtime_success_preserves_existing_firmware_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fallback").mkdir()
            (root / "fallback/owner-marker").write_text("preserve")
            result, calls = self.load(root, "runtime", 0)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls[-2:], ["module:dockchannel-hid", "module:aop"])
            self.assertEqual((root / "fallback/owner-marker").read_text(), "preserve")
