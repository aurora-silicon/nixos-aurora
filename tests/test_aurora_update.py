import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
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


def git(*arguments, cwd):
    return subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                           "-c", "init.defaultBranch=main", *arguments], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


class ChannelHistoryTests(unittest.TestCase):
    """A channel update is taken only from main's history and only forwards."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="aurora channel ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        upstream = self.root / "upstream"
        upstream.mkdir()
        git("init", "--quiet", cwd=upstream)
        self.commits = []
        for index in range(3):
            (upstream / "file").write_text(str(index))
            git("add", "file", cwd=upstream)
            git("commit", "--quiet", "-m", f"reviewed {index}", cwd=upstream)
            self.commits.append(git("rev-parse", "HEAD", cwd=upstream))
        git("checkout", "--quiet", "-b", "channel-testing", self.commits[1], cwd=upstream)
        (upstream / "file").write_text("unreviewed")
        git("commit", "--quiet", "-am", "unreviewed", cwd=upstream)
        self.unreviewed = git("rev-parse", "HEAD", cwd=upstream)
        git("checkout", "--quiet", "main", cwd=upstream)
        self.history = str(upstream)
        self.consumer = self.root / "consumer flake"
        self.consumer.mkdir()
        self.lock = self.consumer / "flake.lock"
        self.lock.write_text(json.dumps(self.lock_for(self.commits[1]), indent=2) + "\n")
        self.lock.chmod(0o640)
        self.saved = self.lock.read_bytes()
        self.log = self.root / "commands.jsonl"
        self.settings = self.root / "settings.json"
        self.system = self.root / "system"
        self.system.mkdir()
        self.current = self.root / "current-system"
        program = f'''#!{sys.executable}
import json, pathlib, sys
root = pathlib.Path({str(self.root)!r})
settings = json.loads((root / "settings.json").read_text())
with (root / "commands.jsonl").open("a") as log:
    log.write(json.dumps([pathlib.Path(sys.argv[0]).name, *sys.argv[1:]]) + "\\n")
if pathlib.Path(sys.argv[0]).name == "fake nix":
    action = sys.argv[2] if sys.argv[1] == "flake" else sys.argv[1]
    if action == "metadata":
        print(json.dumps({{"resolvedUrl": settings["reference"]}}))
    elif action == "update":
        (root / "consumer flake" / "flake.lock").write_text(json.dumps(settings["lock"]))
    elif action == "eval":
        print(settings["system"])
'''
        self.nix = self.root / "fake nix"
        self.rebuild = self.root / "fake rebuild"
        for command in (self.nix, self.rebuild):
            command.write_text(program)
            command.chmod(0o755)

    def lock_for(self, revision, ref="channel-testing", owner="aurora-silicon"):
        return {"version": 7, "root": "root", "nodes": {
            "root": {"inputs": {"aurora": "aurora"}},
            "aurora": {"locked": {"type": "github", "owner": owner, "repo": "nixos-aurora", "rev": revision},
                       "original": {"type": "github", "owner": "aurora-silicon", "repo": "nixos-aurora",
                                    "ref": ref}}}}

    def update(self, lock, *arguments, history=None, git="git"):
        self.settings.write_text(json.dumps({
            "reference": "path:" + urllib.parse.quote(str(self.consumer)), "lock": lock,
            "system": str(self.system)}))
        error = io.StringIO()
        with mock.patch.object(updater.os, "geteuid", return_value=0), contextlib.redirect_stderr(error):
            status = updater.main(["--flake", "./consumer#host", *arguments], state_dir=self.root / "state",
                                  current_system=self.current, nix=str(self.nix), rebuild=str(self.rebuild),
                                  owner_uid=os.getuid(), git=git, history_url=history or self.history)
        return status, error.getvalue()

    def actions(self):
        return [entry[0] if entry[0] == "fake rebuild" else entry[1] if entry[1] != "flake" else entry[2]
                for entry in map(json.loads, self.log.read_text().splitlines())]

    def assert_refused(self, status, error, reason):
        self.assertEqual(status, 1)
        self.assertIn(reason, error)
        self.assertIn("nothing was updated", error)
        self.assertEqual(self.lock.read_bytes(), self.saved)
        self.assertEqual(stat.S_IMODE(self.lock.stat().st_mode), 0o640)
        self.assertEqual(self.actions(), ["metadata", "update"])

    def test_newer_reviewed_commit_is_taken(self):
        status, error = self.update(self.lock_for(self.commits[2]))
        self.assertEqual(status, 0, error)
        self.assertEqual(self.actions(), ["metadata", "update", "eval", "fake rebuild"])
        self.assertEqual(json.loads(self.lock.read_text())["nodes"]["aurora"]["locked"]["rev"], self.commits[2])

    def test_commit_outside_reviewed_history_is_refused(self):
        status, error = self.update(self.lock_for(self.unreviewed))
        self.assert_refused(status, error, "not in the reviewed history")

    def test_older_commit_needs_an_explicit_downgrade(self):
        status, error = self.update(self.lock_for(self.commits[0]))
        self.assert_refused(status, error, "does not include the installed")
        self.log.unlink()
        status, error = self.update(self.lock_for(self.commits[0]), "--allow-downgrade")
        self.assertEqual(status, 0, error)
        self.assertEqual(self.actions(), ["metadata", "update", "eval", "fake rebuild"])

    def test_downgrade_still_needs_reviewed_history(self):
        status, error = self.update(self.lock_for(self.unreviewed), "--allow-downgrade")
        self.assert_refused(status, error, "not in the reviewed history")

    def test_unreachable_history_refuses_the_update(self):
        status, error = self.update(self.lock_for(self.commits[2]), history=str(self.root / "missing"))
        self.assert_refused(status, error, "could not fetch the history")

    def test_channel_locked_to_another_repository_is_refused(self):
        status, error = self.update(self.lock_for(self.commits[2], owner="someone-else"))
        self.assertEqual(status, 1)
        self.assertIn("is not locked to a aurora-silicon/nixos-aurora commit", error)
        self.assertEqual(self.lock.read_bytes(), self.saved)

    def test_unchanged_channel_is_still_checked_against_history(self):
        status, error = self.update(self.lock_for(self.commits[1]), history=str(self.root / "missing"))
        self.assert_refused(status, error, "could not fetch the history")
        self.log.unlink()
        status, error = self.update(self.lock_for(self.commits[1]))
        self.assertEqual(status, 0, error)

    def test_unreviewed_commit_already_in_the_lock_is_refused(self):
        # A hand-run `nix flake update` put the channel's commit in the lock first.
        self.lock.write_text(json.dumps(self.lock_for(self.unreviewed)))
        self.saved = self.lock.read_bytes()
        status, error = self.update(self.lock_for(self.unreviewed))
        self.assert_refused(status, error, "not in the reviewed history")

    def test_interrupted_check_restores_the_lock_and_the_next_run_still_refuses(self):
        self.settings.write_text("{}")
        with mock.patch.object(updater, "check_channel", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.update(self.lock_for(self.unreviewed))
        self.assertEqual(self.lock.read_bytes(), self.saved)
        self.log.unlink()
        status, error = self.update(self.lock_for(self.unreviewed))
        self.assert_refused(status, error, "not in the reviewed history")

    def test_missing_git_restores_the_lock_and_the_next_run_still_refuses(self):
        status, error = self.update(self.lock_for(self.unreviewed), git=str(self.root / "no-git"))
        self.assertEqual(status, 1)
        self.assertEqual(self.lock.read_bytes(), self.saved)
        self.assertEqual(self.actions(), ["metadata", "update"])
        self.log.unlink()
        status, error = self.update(self.lock_for(self.unreviewed))
        self.assert_refused(status, error, "not in the reviewed history")

    def test_restored_lock_keeps_its_owner(self):
        metadata = self.lock.stat()
        with mock.patch.object(updater.os, "chown") as chown:
            status, error = self.update(self.lock_for(self.unreviewed))
        self.assert_refused(status, error, "not in the reviewed history")
        chown.assert_called_once()
        self.assertEqual(chown.call_args.args[1:], (metadata.st_uid, metadata.st_gid))

    def test_inputs_that_follow_no_channel_are_not_checked(self):
        self.lock.write_text(json.dumps(self.lock_for(self.commits[1], ref=self.commits[1])))
        status, error = self.update(self.lock_for(self.unreviewed, ref=self.commits[1]),
                                    history=str(self.root / "missing"))
        self.assertEqual(status, 0, error)

    def test_remote_consumer_following_a_channel_is_refused_before_update(self):
        self.settings.write_text("{}")
        with mock.patch.object(updater.subprocess, "check_output", return_value=json.dumps({
                "resolvedUrl": "github:someone/consumer", "locks": self.lock_for(self.commits[1])})), \
                mock.patch.object(updater.subprocess, "run") as run, \
                mock.patch.object(updater.os, "geteuid", return_value=0), \
                contextlib.redirect_stderr(io.StringIO()) as error:
            status = updater.main(["--flake", "github:someone/consumer#host"], state_dir=self.root / "state",
                                  current_system=self.current, owner_uid=os.getuid())
        self.assertEqual(status, 1)
        self.assertIn("must be local", error.getvalue())
        run.assert_not_called()
