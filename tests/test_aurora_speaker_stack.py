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

    def test_select_speakersafetyd_installs_dropin_masks_v2_and_survives_upgrade(self):
        rc = self.mod.main([
            "--config", str(self.cfg),
            "--root", str(self.root),
            "--distro", "fedora",
            "select", "speakersafetyd", "--no-install", "--no-switch",
        ])
        self.assertEqual(rc, 0)
        self.assertEqual(self.mod.read_selection(self.cfg), ("speakersafetyd", True))

        etc_sd = self.root / "etc/systemd/system"
        for unit in self.mod.SGV2_SYSTEM_UNITS + ("aurora-speaker-upgrade.service",):
            link = etc_sd / unit
            self.assertTrue(link.is_symlink(), unit)
            self.assertEqual(os.readlink(link), "/dev/null")

        dropin = etc_sd / "speakersafetyd.service.d/50-aurora-speaker-stack.conf"
        self.assertTrue(dropin.is_file())
        self.assertIn("ExecStartPre=+/usr/bin/aurora-speaker-stack interlock-apply", dropin.read_text())

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
        self.assertTrue(dropin.is_file())

    def test_select_speakersafetyd_install_failure_leaves_v2_and_config_untouched(self):
        with mock.patch("os.geteuid", return_value=0), \
             mock.patch.object(
                 self.mod,
                 "find_speaker_cards",
                 return_value=[{"card": "0", "id": "AppleJ413", "interface_control": "dual"}],
             ), \
             mock.patch.object(
                 self.mod,
                 "install_speakersafetyd",
                 side_effect=RuntimeError("dnf failed (offline)"),
             ), \
             mock.patch.object(self.mod, "mask_units") as mask_mock, \
             mock.patch.object(self.mod, "install_speakersafetyd_dropin") as dropin_mock:
            rc = self.mod.main([
                "--config", str(self.cfg),
                "--distro", "fedora",
                "select", "speakersafetyd",
            ])
        self.assertEqual(rc, 1)
        self.assertFalse(self.cfg.exists())
        mask_mock.assert_not_called()
        dropin_mock.assert_not_called()

    def test_select_speakersafetyd_sgv2_only_kernel_refuses_before_touching_state(self):
        with mock.patch("os.geteuid", return_value=0), \
             mock.patch.object(
                 self.mod,
                 "find_speaker_cards",
                 return_value=[{"card": "0", "id": "AppleJ413", "interface_control": "sgv2-only"}],
             ), \
             mock.patch.object(self.mod, "install_speakersafetyd") as install_mock, \
             mock.patch.object(self.mod, "mask_units") as mask_mock, \
             mock.patch.object(self.mod, "install_speakersafetyd_dropin") as dropin_mock:
            rc = self.mod.main([
                "--config", str(self.cfg),
                "--distro", "fedora",
                "select", "speakersafetyd",
            ])
        self.assertEqual(rc, 1)
        self.assertFalse(self.cfg.exists())
        install_mock.assert_not_called()
        mask_mock.assert_not_called()
        dropin_mock.assert_not_called()

    def test_select_speakersafetyd_interlock_write_failure_rolls_back_v2(self):
        with mock.patch("os.geteuid", return_value=0), \
             mock.patch.object(
                 self.mod,
                 "find_speaker_cards",
                 return_value=[{"card": "0", "id": "AppleJ413", "interface_control": "dual"}],
             ), \
             mock.patch.object(self.mod, "install_speakersafetyd"), \
             mock.patch.object(self.mod, "find_provision_helper", return_value=None), \
             mock.patch.object(self.mod, "switch_kernel_interlock", return_value=False), \
             mock.patch.object(self.mod, "systemd_running", return_value=False), \
             mock.patch.object(self.mod, "mask_units") as mask_mock, \
             mock.patch.object(self.mod, "unmask_and_preset_units") as unmask_mock, \
             mock.patch.object(self.mod, "remove_speakersafetyd_dropin") as rm_dropin_mock, \
             mock.patch.object(self.mod, "install_speakersafetyd_dropin") as add_dropin_mock:
            rc = self.mod.main([
                "--config", str(self.cfg),
                "--distro", "fedora",
                "select", "speakersafetyd",
            ])
        self.assertEqual(rc, 1)
        self.assertFalse(self.cfg.exists())
        add_dropin_mock.assert_not_called()
        rm_dropin_mock.assert_called_once()
        # First call masked v2; rollback masked legacy units and restored v2.
        self.assertEqual(mask_mock.call_count, 2)
        self.assertEqual(mask_mock.call_args_list[1].args[0], self.mod.LEGACY_UNITS)
        unmask_mock.assert_called_once()

    def test_select_speakersafetyd_service_restart_failure_rolls_back_v2(self):
        def fake_run(cmd, check=False):
            if cmd == ["systemctl", "restart", "speakersafetyd.service"]:
                return mock.Mock(returncode=1, stdout="", stderr="Job failed")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("os.geteuid", return_value=0), \
             mock.patch.object(
                 self.mod,
                 "find_speaker_cards",
                 return_value=[{"card": "0", "id": "AppleJ413", "interface_control": "dual"}],
             ), \
             mock.patch.object(self.mod, "install_speakersafetyd"), \
             mock.patch.object(self.mod, "find_provision_helper", return_value=None), \
             mock.patch.object(self.mod, "switch_kernel_interlock", return_value=True), \
             mock.patch.object(self.mod, "systemd_running", return_value=True), \
             mock.patch("shutil.which", return_value="/usr/bin/systemctl"), \
             mock.patch.object(self.mod, "run_cmd", side_effect=fake_run), \
             mock.patch.object(self.mod, "mask_units") as mask_mock, \
             mock.patch.object(self.mod, "unmask_and_preset_units") as unmask_mock, \
             mock.patch.object(self.mod, "install_speakersafetyd_dropin") as add_dropin_mock, \
             mock.patch.object(self.mod, "remove_speakersafetyd_dropin") as rm_dropin_mock:
            rc = self.mod.main([
                "--config", str(self.cfg),
                "--distro", "fedora",
                "select", "speakersafetyd",
            ])
        self.assertEqual(rc, 1)
        self.assertFalse(self.cfg.exists())
        add_dropin_mock.assert_called_once()
        rm_dropin_mock.assert_called_once()
        self.assertEqual(mask_mock.call_args_list[-1].args[0], self.mod.LEGACY_UNITS)
        self.assertEqual(
            unmask_mock.call_args_list[-1].args[0],
            self.mod.SGV2_SYSTEM_UNITS + ("aurora-speaker-upgrade.service",),
        )

    def test_migrate_default_masks_legacy_removes_dropin_and_unmasks_v2(self):
        etc_sd = self.root / "etc/systemd/system"
        etc_sd.mkdir(parents=True, exist_ok=True)
        (etc_sd / "speakerguardd-v2.service").symlink_to("/dev/null")
        self.mod.install_speakersafetyd_dropin(root=self.root)

        rc = self.mod.main([
            "--config", str(self.cfg),
            "--root", str(self.root),
            "migrate", "--on-upgrade",
        ])
        self.assertEqual(rc, 0)
        self.assertEqual(os.readlink(etc_sd / "speakersafetyd.service"), "/dev/null")
        self.assertEqual(os.readlink(etc_sd / "speakerguardd.service"), "/dev/null")
        self.assertFalse((etc_sd / "speakerguardd-v2.service").exists())
        self.assertFalse((etc_sd / "speakersafetyd.service.d/50-aurora-speaker-stack.conf").exists())

    def test_select_sgv2_clears_v2_masks_dropin_and_masks_legacy(self):
        self.mod.main([
            "--config", str(self.cfg),
            "--root", str(self.root),
            "--distro", "fedora",
            "select", "speakersafetyd", "--no-install", "--no-switch",
        ])
        rc = self.mod.main([
            "--config", str(self.cfg),
            "--root", str(self.root),
            "--distro", "fedora",
            "select", "sgv2", "--no-switch",
        ])
        self.assertEqual(rc, 0)
        self.assertEqual(self.mod.read_selection(self.cfg), ("sgv2", True))
        etc_sd = self.root / "etc/systemd/system"
        self.assertFalse((etc_sd / "speakerguardd-v2.service").exists())
        self.assertFalse((etc_sd / "speakersafetyd.service.d/50-aurora-speaker-stack.conf").exists())
        self.assertEqual(os.readlink(etc_sd / "speakersafetyd.service"), "/dev/null")
        self.assertEqual(os.readlink(etc_sd / "speakerguardd.service"), "/dev/null")

    def test_interlock_apply_fails_closed_unless_opted_out(self):
        # Missing config (default sgv2) -> refuse.
        self.assertEqual(self.mod.main(["--config", str(self.cfg), "interlock-apply"]), 1)
        # Explicit sgv2 -> refuse.
        self.mod.write_selection("sgv2", self.cfg)
        self.assertEqual(self.mod.main(["--config", str(self.cfg), "interlock-apply"]), 1)
        # Explicit speakersafetyd -> fails closed when amixer is missing.
        self.mod.write_selection("speakersafetyd", self.cfg)
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(self.mod.main(["--config", str(self.cfg), "interlock-apply"]), 1)
        # Explicit speakersafetyd -> writes Speaker Volume Unlock via cset name=....
        with mock.patch("shutil.which", return_value="/usr/bin/amixer"), \
             mock.patch.object(
                 self.mod,
                 "find_speaker_cards",
                 return_value=[{"card": "0", "id": "AppleJ413", "interface_control": "dual"}],
             ), mock.patch.object(
                 self.mod,
                 "run_cmd",
                 return_value=mock.Mock(returncode=0, stdout="", stderr=""),
             ) as run_mock:
            self.assertEqual(self.mod.main(["--config", str(self.cfg), "interlock-apply"]), 0)
            run_mock.assert_called_once()
            self.assertEqual(
                run_mock.call_args.args[0],
                ["amixer", "-c", "0", "-q", "cset", "name=Speaker Protection Interface", "Speaker Volume Unlock"],
            )

    def test_find_speaker_cards_uses_cget_for_inactive_controls(self):
        sys_sound = self.root / "sys/class/sound"
        card0 = sys_sound / "card0"
        card0.mkdir(parents=True)
        (card0 / "id").write_text("AppleJ413\n", encoding="utf-8")

        cget_out = (
            "numid=40,iface=MIXER,name='Speaker Protection Interface'\n"
            "  ; type=ENUMERATED,access=rw-----I,values=1,items=2\n"
            "  ; Item #0 'Speaker Volume Unlock'\n"
            "  ; Item #1 'Speaker Protection'\n"
            "  : values=1\n"
        )

        def fake_run(cmd, check=False, env=None):
            self.assertNotIn("controls", cmd)
            if cmd == ["amixer", "-c", "0", "cget", "name=Speaker Protection Interface"]:
                return mock.Mock(returncode=0, stdout=cget_out, stderr="")
            return mock.Mock(returncode=1, stdout="", stderr="amixer: Cannot find the given element from control hw:0\n")

        with mock.patch("shutil.which", return_value="/usr/bin/amixer"), \
             mock.patch.object(self.mod, "run_cmd", side_effect=fake_run):
            cards = self.mod.find_speaker_cards(sys_sound, strict=True)
        self.assertEqual(
            cards,
            [{"card": "0", "id": "AppleJ413", "interface_control": "dual", "interface_value": "Speaker Protection"}],
        )

    def test_select_speakersafetyd_deactivates_v2_graph(self):
        calls = []

        def fake_run(cmd, check=False, env=None):
            calls.append(cmd)
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("os.geteuid", return_value=0), \
             mock.patch.object(
                 self.mod,
                 "find_speaker_cards",
                 return_value=[{"card": "0", "id": "AppleJ413", "interface_control": "dual"}],
             ), \
             mock.patch.object(self.mod, "install_speakersafetyd"), \
             mock.patch.object(self.mod, "find_provision_helper", return_value="/usr/libexec/speakerguardd-v2/speakerguardd-provision"), \
             mock.patch.object(self.mod, "switch_kernel_interlock", return_value=True), \
             mock.patch.object(self.mod, "systemd_running", return_value=True), \
             mock.patch("shutil.which", return_value="/usr/bin/systemctl"), \
             mock.patch.object(self.mod, "run_cmd", side_effect=fake_run), \
             mock.patch.object(self.mod, "mask_units"), \
             mock.patch.object(self.mod, "unmask_and_preset_units"), \
             mock.patch.object(self.mod, "install_speakersafetyd_dropin"):
            rc = self.mod.main([
                "--config", str(self.cfg),
                "--distro", "fedora",
                "select", "speakersafetyd",
            ])
        self.assertEqual(rc, 0)
        self.assertIn(
            ["/usr/libexec/speakerguardd-v2/speakerguardd-provision", "deactivate", "--graph-unit", "speakerguardd-v2-graph.service"],
            calls,
        )

    def test_nixos_select_writes_only_declarative_dropin_not_etc_conf(self):
        rc = self.mod.main([
            "--config", str(self.cfg),
            "--root", str(self.root),
            "--distro", "nixos",
            "select", "speakersafetyd", "--no-switch",
        ])
        self.assertEqual(rc, 0)
        dropin = self.root / "etc/nixos/aurora-speaker-stack.nix"
        self.assertIn('aurora.speakers.stack = "speakersafetyd";', dropin.read_text())
        # NixOS owns /etc/aurora/speaker-stack.conf via environment.etc.
        self.assertFalse(self.cfg.exists())

    def test_nixos_select_rolls_back_dropin_on_rebuild_failure(self):
        dropin = self.root / "etc/nixos/aurora-speaker-stack.nix"
        dropin.parent.mkdir(parents=True, exist_ok=True)
        prior = '{ ... }: {\n  aurora.speakers.stack = "sgv2";\n}\n'
        dropin.write_text(prior, encoding="utf-8")

        orig_is_file = Path.is_file

        def fake_is_file(path_obj):
            if str(path_obj) == "/etc/nixos/configuration.nix":
                return True
            return orig_is_file(path_obj)

        with mock.patch("os.geteuid", return_value=0), \
             mock.patch.object(self.mod, "NIXOS_DROPIN", dropin), \
             mock.patch.object(self.mod, "kernel_supports_stack", return_value=True), \
             mock.patch.object(Path, "is_file", fake_is_file), \
             mock.patch("shutil.which", return_value="/run/current-system/sw/bin/nixos-rebuild"), \
             mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)):
            rc = self.mod.main([
                "--config", str(self.cfg),
                "--distro", "nixos",
                "select", "speakersafetyd",
            ])
        self.assertEqual(rc, 1)
        self.assertEqual(dropin.read_text(encoding="utf-8"), prior)

    def test_status_json_output(self):
        self.mod.write_selection("speakersafetyd", self.cfg)
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf), \
             mock.patch.object(self.mod, "unit_state", return_value={"enabled": "masked", "active": "inactive"}), \
             mock.patch.object(self.mod, "find_speaker_cards", return_value=[]):
            rc = self.mod.main(["--config", str(self.cfg), "--distro", "fedora", "status", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["selected"], "speakersafetyd")
        self.assertTrue(data["explicit_override"])
        self.assertEqual(data["distro"], "fedora")

    def test_switch_kernel_interlock_sgv2_only_refuses_speakersafetyd(self):
        with mock.patch.object(
            self.mod,
            "find_speaker_cards",
            return_value=[{"card": "0", "id": "AppleJ413", "interface_control": "sgv2-only"}],
        ):
            self.assertFalse(self.mod.switch_kernel_interlock("speakersafetyd"))
            self.assertTrue(self.mod.switch_kernel_interlock("sgv2"))


if __name__ == "__main__":
    unittest.main()
