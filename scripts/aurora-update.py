#!/usr/bin/env python3
"""Update a declared consumer flake, remembering only verified local switches."""
import argparse
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile


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
         current_system=Path("/run/current-system"), nix="nix", rebuild="nixos-rebuild", owner_uid=0):
    parser = argparse.ArgumentParser(prog="aurora-update", description=__doc__, allow_abbrev=False)
    parser.add_argument("--flake", help="consumer flake reference, optionally followed by #configuration")
    parser.add_argument("--input", help="Aurora input name (default: the installed configuration's setting)")
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
        subprocess.run([nix, "flake", "update", input_name, "--flake", reference, *flags], check=True)
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
