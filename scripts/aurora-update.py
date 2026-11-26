#!/usr/bin/env python3
"""Update a declared consumer flake, remembering only verified local switches."""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import tempfile
import urllib.parse

OWNER, REPO = "aurora-silicon", "nixos-aurora"
CHANNELS = ("channel-testing", "channel-stable")
HISTORY_URL = f"https://github.com/{OWNER}/{REPO}.git"
HISTORY_BRANCH = "main"
COMMIT = re.compile(r"[0-9a-f]{40}")


def active_system(current_system):
    try:
        return str(Path(current_system).resolve(strict=True))
    except OSError:
        return None


def remembered_source(state_dir, generation, owner_uid):
    if generation is None:
        return None
    path = Path(state_dir) / "source.json"
    try:
        directory = Path(state_dir).lstat()
        metadata = path.lstat()
        if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != owner_uid
                or directory.st_mode & 0o022 or not stat.S_ISREG(metadata.st_mode)):
            return None
        with path.open() as source:
            metadata = os.fstat(source.fileno())
            if metadata.st_uid != owner_uid or stat.S_IMODE(metadata.st_mode) & 0o077:
                return None
            value = json.load(source)
        if value.get("version") != 1 or value.get("generation") != generation:
            return None
        if not all(isinstance(value.get(key), str) and value[key] for key in ("ref", "selector", "input")):
            return None
        return value
    except (OSError, ValueError, AttributeError):
        return None


def remember(state_dir, value, owner_uid):
    directory = Path(state_dir)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = directory.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != owner_uid or metadata.st_mode & 0o022:
        raise ValueError("updater state directory must be owned by root and not writable by other users")
    directory.chmod(0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".source-", dir=directory)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(value, output)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, directory / "source.json")
    finally:
        Path(temporary).unlink(missing_ok=True)


def aurora_input(lock, input_name):
    """The `(channel, revision)` of the locked Aurora input, from a flake.lock.

    `channel` is the channel ref the input follows, or None when it follows
    anything else. `revision` is the locked nixos-aurora commit, or None when
    the input is not locked to this repository on GitHub.
    """
    try:
        name = lock["nodes"][lock["root"]]["inputs"][input_name]
        node = lock["nodes"][name]
        original, locked = node.get("original", {}), node.get("locked", {})
    except (KeyError, TypeError, AttributeError):
        return None, None
    def upstream(value):
        return (isinstance(value, dict) and value.get("type") == "github"
                and str(value.get("owner", "")).lower() == OWNER and str(value.get("repo", "")).lower() == REPO)
    channel = original.get("ref") if upstream(original) and original.get("ref") in CHANNELS else None
    revision = locked.get("rev") if upstream(locked) else None
    return channel, revision if isinstance(revision, str) and COMMIT.fullmatch(revision) else None


def lock_path(reference):
    """flake.lock of a local consumer flake reference, or None for other references."""
    parts = urllib.parse.urlsplit(reference)
    if parts.scheme not in ("path", "git+file"):
        return None
    subdirectory = urllib.parse.parse_qs(parts.query).get("dir", [""])[0]
    return Path(urllib.parse.unquote(parts.path), subdirectory, "flake.lock")


def read_lock(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None


def restore_lock(path, saved, metadata):
    """Put back the consumer lock exactly as it was before the update: bytes, mode and owner."""
    if saved is None:
        path.unlink(missing_ok=True)
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".flake.lock-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(saved)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, stat.S_IMODE(metadata.st_mode))
        if os.geteuid() == 0:
            try:
                os.chown(temporary, metadata.st_uid, metadata.st_gid)
            except OSError:
                pass
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def check_channel(channel, previous, revision, allow_downgrade, git="git", url=HISTORY_URL):
    """Refuse a channel commit outside reviewed history, or older than `previous` (None: no check).

    Every commit a channel serves comes from nixos-aurora's main branch, which
    changes only through reviewed pull requests. Only main's commit graph is
    fetched (no trees or files), into a temporary repository.
    """
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1"}
    with tempfile.TemporaryDirectory(prefix="aurora-update-history-") as temporary:
        history = str(Path(temporary) / "history.git")
        fetched = subprocess.run([git, "clone", "--quiet", "--bare", "--no-tags", "--single-branch",
                                  "--branch", HISTORY_BRANCH, "--filter=tree:0", url, history],
                                 env=environment, capture_output=True, text=True)
        if fetched.returncode:
            raise ValueError(f"could not fetch the history of {OWNER}/{REPO} {HISTORY_BRANCH} to check "
                             f"{channel}: {fetched.stderr.strip()}")

        def contains(ancestor, descendant):
            return subprocess.run([git, "-C", history, "merge-base", "--is-ancestor", ancestor, descendant],
                                  env=environment, capture_output=True).returncode == 0

        if not contains(revision, f"refs/heads/{HISTORY_BRANCH}"):
            raise ValueError(f"{channel} names {revision}, which is not in the reviewed history of "
                             f"{OWNER}/{REPO} {HISTORY_BRANCH}")
        if previous and not allow_downgrade and not contains(previous, revision):
            raise ValueError(f"{channel} names {revision}, which does not include the installed {previous}; "
                             "pass --allow-downgrade only to take an announced rollback")


def nix_flags(arguments):
    """Evaluation settings shared with nixos-rebuild; keep its argv intact."""
    flags = []
    unary = {"--impure", "--offline", "--refresh", "--show-trace", "--no-write-lock-file", "--no-update-lock-file"}
    arity = {"--option": 2, "--override-input": 2, "--override-flake": 2,
             "--store": 1, "--include": 1, "-I": 1,
             "--extra-experimental-features": 1, "--experimental-features": 1}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in unary:
            flags.append(argument)
        elif argument in arity:
            count = arity[argument]
            if len(arguments) <= index + count:
                raise ValueError(f"{argument} needs {count} argument(s)")
            flags.extend(arguments[index:index + count + 1])
            index += count
        elif any(argument.startswith(name + "=") for name, count in arity.items() if count == 1):
            flags.append(argument)
        index += 1
    return flags


def main(argv=None, *, state_dir=Path("/var/lib/aurora/update"),
         current_system=Path("/run/current-system"), nix="nix", rebuild="nixos-rebuild", owner_uid=0,
         git="git", history_url=HISTORY_URL):
    parser = argparse.ArgumentParser(prog="aurora-update", description=__doc__, allow_abbrev=False)
    parser.add_argument("--flake", help="consumer flake reference, optionally followed by #configuration")
    parser.add_argument("--input", help="Aurora input name (default: the installed configuration's setting)")
    parser.add_argument("--allow-downgrade", action="store_true",
                        help="accept a channel commit that does not include the installed one (an announced rollback)")
    parser.add_argument("--configured-flake", help=argparse.SUPPRESS)
    parser.add_argument("--configured-input", default="aurora", help=argparse.SUPPRESS)
    parser.add_argument("--factory-flake", help=argparse.SUPPRESS)
    options, arguments = parser.parse_known_args(argv)
    if os.geteuid() != 0:
        print("aurora-update: run it with sudo", file=sys.stderr)
        return 1
    try:
        previous = remembered_source(state_dir, active_system(current_system), owner_uid)
        carry_memory = options.flake is not None
        if options.flake is not None:
            source = options.flake
            input_name = options.input if options.input is not None else options.configured_input
        elif previous is not None:
            source = previous["ref"] + "#" + previous["selector"]
            input_name = options.input if options.input is not None else previous["input"]
            carry_memory = True
        else:
            source = options.configured_flake or options.factory_flake
            input_name = options.input if options.input is not None else options.configured_input
        if not source:
            raise ValueError("no consumer flake is known; pass --flake REF#CONFIG or set aurora.update.flake")
        if not input_name:
            raise ValueError("the Aurora input name must not be empty")
        reference, _, selector = source.partition("#")
        if not reference:
            raise ValueError("--flake needs a nonempty consumer reference")
        selector = selector or socket.gethostname() or "default"
        # nixos-rebuild embeds this name in a quoted Nix attribute. Its parser
        # cannot preserve these characters as literal configuration names.
        if any(character in selector for character in ('"', "\\", "#", "${")) or any(
                ord(character) < 32 or ord(character) == 127 for character in selector):
            raise ValueError("configuration selector contains characters unsupported by nixos-rebuild")
        flags = nix_flags(arguments)
        metadata = json.loads(subprocess.check_output(
            [nix, "flake", "metadata", "--json", "--no-write-lock-file", reference, *flags], text=True))
        reference = metadata.get("resolvedUrl")
        if not isinstance(reference, str) or not reference or "#" in reference:
            raise ValueError("Nix metadata did not provide a canonical flake reference")
        lock = lock_path(reference)
        saved = saved_metadata = None
        if lock is not None:
            try:
                saved_metadata = lock.stat()
                saved = lock.read_bytes()
            except FileNotFoundError:
                pass
        following, installed = aurora_input(metadata.get("locks") or (json.loads(saved) if saved else None),
                                            input_name)
        if following is not None and lock is None:
            raise ValueError(f"the {input_name} input follows {following}, so its consumer flake must be local")
        try:
            subprocess.run([nix, "flake", "update", input_name, "--flake", reference, *flags], check=True)
            if lock is not None:
                # The channel ref is only a pointer: build what it names only from
                # reviewed history, and never older than what was installed. The
                # history check runs every time, also for a commit already in the
                # lock, which a hand-run `nix flake update` may have put there.
                channel, revision = aurora_input(read_lock(lock), input_name)
                if channel is not None and revision is None:
                    raise ValueError(f"the {input_name} input follows {channel} but is not locked to a "
                                     f"{OWNER}/{REPO} commit")
                if channel is not None:
                    check_channel(channel, installed if revision != installed else None, revision,
                                  options.allow_downgrade, git, history_url)
        except BaseException as error:
            # Whatever stops the check, including Ctrl-C, leaves the lock as it was.
            if lock is not None:
                restore_lock(lock, saved, saved_metadata)
            if isinstance(error, ValueError):
                raise ValueError(f"{error}; nothing was updated") from error
            raise
        target = f"{reference}#nixosConfigurations.{json.dumps(selector, ensure_ascii=False)}.config.system.build.toplevel"
        expected = subprocess.check_output([nix, "eval", "--raw", target, *flags], text=True).strip()
        if not expected.startswith("/"):
            raise ValueError("Nix did not return an absolute system output path")
        expected = str(Path(expected).resolve())
        subprocess.run([rebuild, "switch", "--flake", reference + "#" + selector, *arguments], check=True)
        remote = any(argument == "--target-host" or argument.startswith("--target-host=") for argument in arguments)
        if carry_memory and not remote:
            if active_system(current_system) == expected:
                remember(state_dir, {"version": 1, "generation": expected, "ref": reference,
                                     "selector": selector, "input": input_name}, owner_uid)
            else:
                print("aurora-update: source not remembered: the evaluated system is not active locally", file=sys.stderr)
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"aurora-update: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
