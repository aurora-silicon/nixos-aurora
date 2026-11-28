import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "speaker-stack/aurora-speaker-stack"


def load_tool():
    loader = importlib.machinery.SourceFileLoader("aurora_speaker_stack", str(TOOL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class SpeakerStackTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "etc/aurora/speaker-stack.conf"

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_selection_is_sgv2_without_config(self):
        stack, explicit = self.mod.read_selection(self.cfg)
        self.assertEqual(stack, "sgv2")
        self.assertFalse(explicit)

    def test_write_and_read_selection_roundtrip(self):
        self.mod.write_selection("speakersafetyd", self.cfg)
        self.assertEqual(os.stat(self.cfg).st_mode & 0o777, 0o644)
        self.assertEqual(self.mod.read_selection(self.cfg), ("speakersafetyd", True))

        self.mod.write_selection("sgv2", self.cfg)
        self.assertEqual(self.mod.read_selection(self.cfg), ("sgv2", True))

    def test_invalid_stack_in_config_raises(self):
        self.cfg.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text("stack=bogus\n", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            self.mod.read_selection(self.cfg)

    def test_select_speakersafetyd_masks_v2_and_survives_upgrade_migrate(self):
        rc = self.mod.main([
            "--config", str(self.cfg),
            "--root", str(self.root),
            "--distro", "alarm",
            "select", "speakersafetyd", "--no-install", "--no-switch",
        ])
        self.assertEqual(rc, 0)
        self.assertEqual(self.mod.read_selection(self.cfg), ("speakersafetyd", True))

        etc_sd = self.root / "etc/systemd/system"
        for unit in self.mod.SGV2_SYSTEM_UNITS + ("aurora-speaker-upgrade.service",):
            link = etc_sd / unit
            self.assertTrue(link.is_symlink(), unit)
            self.assertEqual(os.readlink(link), "/dev/null")

        # Subsequent package upgrade migration MUST respect the user opt-out.
        rc = self.mod.main([
            "--config", str(self.cfg),
            "--root", str(self.root),
            "migrate", "--on-upgrade",
        ])
        self.assertEqual(rc, 0)
        self.assertEqual(os.readlink(etc_sd / "speakerguardd-v2.service"), "/dev/null")
        self.assertEqual(os.readlink(etc_sd / "aurora-speaker-upgrade.service"), "/dev/null")
        self.assertFalse((etc_sd / "speakersafetyd.service").exists())

    def test_migrate_default_masks_legacy_and_unmasks_v2(self):
        etc_sd = self.root / "etc/systemd/system"
        etc_sd.mkdir(parents=True, exist_ok=True)
        (etc_sd / "speakerguardd-v2.service").symlink_to("/dev/null")

        rc = self.mod.main([
            "--config", str(self.cfg),
            "--root", str(self.root),
            "migrate", "--on-upgrade",
        ])
        self.assertEqual(rc, 0)
        self.assertEqual(os.readlink(etc_sd / "speakersafetyd.service"), "/dev/null")
        self.assertEqual(os.readlink(etc_sd / "speakerguardd.service"), "/dev/null")
        self.assertFalse((etc_sd / "speakerguardd-v2.service").exists())

    def test_select_sgv2_clears_v2_masks_and_masks_legacy(self):
        self.mod.main([
            "--config", str(self.cfg),
            "--root", str(self.root),
            "--distro", "alarm",
            "select", "speakersafetyd", "--no-install", "--no-switch",
        ])
        rc = self.mod.main([
            "--config", str(self.cfg),
            "--root", str(self.root),
            "--distro", "alarm",
            "select", "sgv2", "--no-switch",
        ])
        self.assertEqual(rc, 0)
        self.assertEqual(self.mod.read_selection(self.cfg), ("sgv2", True))
        etc_sd = self.root / "etc/systemd/system"
        self.assertFalse((etc_sd / "speakerguardd-v2.service").exists())
        self.assertEqual(os.readlink(etc_sd / "speakersafetyd.service"), "/dev/null")
        self.assertEqual(os.readlink(etc_sd / "speakerguardd.service"), "/dev/null")

    def test_nixos_select_writes_declarative_dropin(self):
        rc = self.mod.main([
            "--config", str(self.cfg),
            "--root", str(self.root),
            "--distro", "nixos",
            "select", "speakersafetyd", "--no-switch",
        ])
        self.assertEqual(rc, 0)
        dropin = self.root / "etc/nixos/aurora-speaker-stack.nix"
        self.assertIn('aurora.speakers.stack = "speakersafetyd";', dropin.read_text())

    def test_status_json_output(self):
        self.mod.write_selection("speakersafetyd", self.cfg)
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf), \
             mock.patch.object(self.mod, "unit_state", return_value={"enabled": "masked", "active": "inactive"}), \
             mock.patch.object(self.mod, "find_speaker_cards", return_value=[]):
            rc = self.mod.main(["--config", str(self.cfg), "--distro", "alarm", "status", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["selected"], "speakersafetyd")
        self.assertTrue(data["explicit_override"])
        self.assertEqual(data["distro"], "alarm")

    def test_switch_kernel_interlock_dual_and_sgv2_only(self):
        with mock.patch.object(
            self.mod,
            "find_speaker_cards",
            return_value=[{"card": "0", "id": "AppleJ413", "interface_control": "dual"}],
        ), mock.patch.object(
            self.mod,
            "run_cmd",
            return_value=mock.Mock(returncode=0, stdout="", stderr=""),
        ) as run_mock:
            self.assertTrue(self.mod.switch_kernel_interlock("speakersafetyd"))
            run_mock.assert_called_once_with(
                ["amixer", "-c", "0", "cset", "name='Speaker Protection Interface'", "Speaker Volume Unlock"]
            )

        with mock.patch.object(
            self.mod,
            "find_speaker_cards",
            return_value=[{"card": "0", "id": "AppleJ413", "interface_control": "sgv2-only"}],
        ):
            self.assertFalse(self.mod.switch_kernel_interlock("speakersafetyd"))
            self.assertTrue(self.mod.switch_kernel_interlock("sgv2"))


if __name__ == "__main__":
    unittest.main()
