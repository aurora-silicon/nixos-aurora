import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("aurora_update", ROOT / "scripts/aurora-update.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class UpdateSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="aurora updater ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.current = self.root / "current-system"
        self.old = self.root / "old-system"
        self.expected = self.root / "new-system"
        self.old.mkdir()
        self.expected.mkdir()
        self.current.symlink_to(self.old)
        self.log = self.root / "commands.jsonl"
        self.config = {"canonical": "git+file:///consumer%20flake", "expected": str(self.expected),
                       "activate": True, "failure": None}
        self.fixture = self.root / "fixture.json"
        program = f'''#!{sys.executable}
import json, os, pathlib, sys
root = pathlib.Path({str(self.root)!r})
settings = json.loads((root / "fixture.json").read_text())
role = pathlib.Path(sys.argv[0]).name
with (root / "commands.jsonl").open("a") as log:
    log.write(json.dumps([role, *sys.argv[1:]]) + "\\n")
if role == "fake nix":
    action = sys.argv[2] if sys.argv[1] == "flake" else sys.argv[1]
    if settings["failure"] == action:
        sys.exit(19)
    if action == "metadata":
        print(json.dumps({{"resolvedUrl": settings["canonical"]}}))
    elif action == "eval":
        print(settings["expected"])
else:
    if settings["failure"] == "rebuild":
        sys.exit(23)
    if settings["activate"]:
        current = root / "current-system"
        current.unlink(missing_ok=True)
        current.symlink_to(settings["expected"])
'''
        self.nix = self.root / "fake nix"
        self.rebuild = self.root / "fake rebuild"
        for command in (self.nix, self.rebuild):
            command.write_text(program)
            command.chmod(0o755)

    def run_update(self, *arguments, uid=0):
        self.fixture.write_text(json.dumps(self.config))
        error = io.StringIO()
        with mock.patch.object(updater.os, "geteuid", return_value=uid), \
                mock.patch.object(updater.socket, "gethostname", return_value="test-host"), \
                contextlib.redirect_stderr(error):
            status = updater.main(list(arguments), state_dir=self.state, current_system=self.current,
                                  nix=str(self.nix), rebuild=str(self.rebuild), owner_uid=os.getuid())
        return status, error.getvalue()

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def memory(self, generation=None, **changes):
        self.state.mkdir(mode=0o700, exist_ok=True)
        value = {"version": 1, "generation": str(generation or self.old),
                 "ref": "git+file:///remembered", "selector": "remembered-host", "input": "remembered-input"}
        value.update(changes)
        path = self.state / "source.json"
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        return path

    def test_explicit_source_canonicalizes_and_overrides_all_fallbacks(self):
        self.memory()
        flags = ["--option", "extra-substituters", "https://cache.example/path with spaces", "--impure"]
        status, error = self.run_update("--configured-flake", "/configured#configured", "--factory-flake",
                                        "/etc/nixos#aurora", "--flake", "./consumer flake#host with spaces",
                                        "--input", "my-aurora", *flags)
        self.assertEqual(status, 0, error)
        calls = self.calls()
        self.assertEqual(calls[0], ["fake nix", "flake", "metadata", "--json", "--no-write-lock-file",
                                    "./consumer flake", *flags])
        self.assertEqual(calls[1], ["fake nix", "flake", "update", "my-aurora", "--flake",
                                    self.config["canonical"], *flags])
        self.assertEqual(calls[2], ["fake nix", "eval", "--raw", self.config["canonical"] +
                                    '#nixosConfigurations."host with spaces".config.system.build.toplevel', *flags])
        self.assertEqual(calls[3], ["fake rebuild", "switch", "--flake",
                                    self.config["canonical"] + "#host with spaces", *flags])
        path = self.state / "source.json"
        value = json.loads(path.read_text())
        self.assertEqual(value, {"version": 1, "ref": self.config["canonical"], "selector": "host with spaces",
                                 "input": "my-aurora", "generation": str(self.expected)})
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        self.assertEqual(list(self.state.glob(".source-*")), [])

    def test_matching_generation_memory_precedes_configuration_and_moves_forward(self):
        path = self.memory()
        status, error = self.run_update("--configured-flake", "/other#other")
        self.assertEqual(status, 0, error)
        calls = self.calls()
        self.assertEqual(calls[0][5], "git+file:///remembered")
        self.assertEqual(calls[1][3], "remembered-input")
        value = json.loads(path.read_text())
        self.assertEqual(value["generation"], str(self.expected))
        self.assertEqual(value["selector"], "remembered-host")

    def test_direct_rebuild_or_rollback_does_not_reuse_other_generation_memory(self):
        path = self.memory(generation=self.expected)
        previous = path.read_bytes()
        status, error = self.run_update("--configured-flake", "./declared#declared")
        self.assertEqual(status, 0, error)
        self.assertEqual(self.calls()[0][5], "./declared")
        self.assertEqual(path.read_bytes(), previous)

    def test_stale_memory_without_declared_source_cannot_guess_a_flake(self):
        self.memory(generation=self.expected)
        status, error = self.run_update()
        self.assertEqual(status, 1)
        self.assertIn("no consumer flake is known", error)
        self.assertEqual(self.calls(), [])

    def test_factory_fallback_is_explicit_and_does_not_create_memory(self):
        status, error = self.run_update("--factory-flake", "/etc/nixos#aurora")
        self.assertEqual(status, 0, error)
        self.assertEqual(self.calls()[0][5], "/etc/nixos")
        self.assertTrue(self.calls()[-1][3].endswith("#aurora"))
        self.assertFalse(self.state.exists())

    def test_reference_without_selector_uses_hostname(self):
        status, error = self.run_update("--flake", "./consumer")
        self.assertEqual(status, 0, error)
        self.assertTrue(self.calls()[-1][3].endswith("#test-host"))

    def test_empty_selector_uses_hostname_like_nixos_rebuild(self):
        status, error = self.run_update("--flake", "./consumer#")
        self.assertEqual(status, 0, error)
        self.assertTrue(self.calls()[-1][3].endswith("#test-host"))

    def test_unsupported_selector_is_rejected_before_any_update(self):
        for selector in ('host"quoted', '${builtins.currentSystem}', 'host\\escaped', 'host#extra', 'host\nline'):
            with self.subTest(selector=selector):
                status, error = self.run_update("--flake", "./consumer#" + selector)
                self.assertEqual(status, 1)
                self.assertIn("unsupported by nixos-rebuild", error)
                self.assertEqual(self.calls(), [])

    def test_failed_update_never_rebuilds_or_replaces_memory(self):
        path = self.memory()
        previous = path.read_bytes()
        self.config["failure"] = "update"
        status, _ = self.run_update("--flake", "./replacement#host")
        self.assertEqual(status, 1)
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(path.read_bytes(), previous)

    def test_failed_rebuild_never_replaces_memory(self):
        path = self.memory()
        previous = path.read_bytes()
        self.config["failure"] = "rebuild"
        status, _ = self.run_update("--flake", "./replacement#host")
        self.assertEqual(status, 1)
        self.assertEqual(path.read_bytes(), previous)

    def test_failed_evaluation_stops_before_activation(self):
        self.config["failure"] = "eval"
        status, _ = self.run_update("--flake", "./consumer#host")
        self.assertEqual(status, 1)
        self.assertEqual(len(self.calls()), 3)
        self.assertFalse(self.state.exists())

    def test_success_without_expected_local_activation_does_not_remember(self):
        self.config["activate"] = False
        status, error = self.run_update("--flake", "./consumer#host")
        self.assertEqual(status, 0, error)
        self.assertIn("source not remembered", error)
        self.assertFalse(self.state.exists())

    def test_remote_target_does_not_remember_even_if_local_output_matches(self):
        status, error = self.run_update("--flake", "./consumer#host", "--target-host", "owner@remote")
        self.assertEqual(status, 0, error)
        self.assertEqual(self.calls()[-1][-2:], ["--target-host", "owner@remote"])
        self.assertFalse(self.state.exists())

    def test_public_or_malformed_state_is_not_trusted(self):
        path = self.memory()
        path.chmod(0o644)
        status, _ = self.run_update()
        self.assertEqual(status, 1)
        self.assertEqual(self.calls(), [])
        path.chmod(0o600)
        path.write_text("not json")
        status, _ = self.run_update()
        self.assertEqual(status, 1)
        self.assertEqual(self.calls(), [])

    def test_missing_active_generation_cannot_match_missing_generation_in_state(self):
        path = self.memory()
        value = json.loads(path.read_text())
        del value["generation"]
        path.write_text(json.dumps(value))
        self.current.unlink()
        status, _ = self.run_update()
        self.assertEqual(status, 1)
        self.assertEqual(self.calls(), [])

    def test_symlinked_state_is_not_followed(self):
        path = self.memory()
        target = self.root / "other-state.json"
        path.rename(target)
        path.symlink_to(target)
        status, _ = self.run_update()
        self.assertEqual(status, 1)
        self.assertEqual(self.calls(), [])

    def test_unsafe_state_directory_is_not_written_after_activation(self):
        self.state.mkdir(mode=0o777)
        self.state.chmod(0o777)
        status, error = self.run_update("--flake", "./consumer#host")
        self.assertEqual(status, 1)
        self.assertIn("not writable by other users", error)
        self.assertEqual(self.current.resolve(), self.expected)
        self.assertFalse((self.state / "source.json").exists())

    def test_empty_input_is_rejected_before_update(self):
        status, _ = self.run_update("--flake", "./consumer#host", "--input", "")
        self.assertEqual(status, 1)
        self.assertEqual(self.calls(), [])

    def test_non_root_runs_no_commands(self):
        status, error = self.run_update("--flake", "./consumer#host", uid=1000)
        self.assertEqual(status, 1)
        self.assertIn("sudo", error)
        self.assertEqual(self.calls(), [])
