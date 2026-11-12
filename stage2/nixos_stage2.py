#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Trial-then-commit Stage 2 updates for NixOS generations.

The trial, verification and commit logic is fedora-aurora's bootchain.py,
copied unchanged beside this file (provenance.json). This adapter supplies
only what differs on NixOS:

- The Stage 2 is built and checked with the system (modules/installed.nix),
  so the installer takes that file instead of composing one from /boot.
- The kernels that must keep booting with the shared device trees are those
  of the generations GRUB lists. Each NixOS generation declares its kernel's
  DT ABI generation in `aurora-dtb-abi`; one without the file has the
  generation of another listed generation with the same kernel, or 1, as
  bootchain.py counts kernels from before the marker.
- The newest bootloader install decides the trial: an armed candidate that
  never booted is withdrawn when a later install selects other bytes.
- Receipts name the candidate's SHA-256 where Fedora names the kernel.
- The built image goes through bootchain.py's sign() (aurora-secboot's
  stage2 hook) before anything is compared or written, so receipts and
  trials name the signed bytes.

Attempts per candidate image and staging on a trial boot after its commit
come from bootchain.py itself (fedora-aurora#207).

  nixos_stage2.py install|check|commit|guard

All inputs come from the environment (see main()); the shell entry points in
scripts/install-stage2.sh and modules/installed.nix set them.
"""
import argparse
from dataclasses import dataclass
import fcntl
import glob
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

_spec = importlib.util.spec_from_file_location('bootchain', Path(__file__).resolve().with_name('bootchain.py'))
bootchain = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bootchain)
Refused = bootchain.Refused


def read_generation(path):
    """A declared DT ABI generation, in bootchain's format; None if undeclared."""
    try:
        value = path.read_text(encoding='ascii')
    except FileNotFoundError:
        return None
    if not re.fullmatch(r'(0|[1-9][0-9]*)\n?', value):
        raise Refused(f'invalid DT ABI generation in {path}')
    return int(value)


@dataclass(frozen=True)
class Entry:
    """A NixOS configuration GRUB lists."""
    toplevel: Path
    profile: Path = None
    number: int = None


class NixosUpdate(bootchain.Update):
    def __init__(self, root=Path('/'), env=None):
        super().__init__(root, env)
        self._generations = None

    # Generations GRUB lists, the way install-grub.pl walks them.

    def profiles(self):
        base = self.path(self.env.get('AURORA_SYSTEM_PROFILES', '/nix/var/nix/profiles'))
        yield base / 'system'
        named = base / 'system-profiles'
        if named.is_dir():
            yield from sorted(p for p in named.iterdir() if re.fullmatch(r'[A-Za-z0-9_]+', p.name))

    def retained(self):
        limit = int(self.env.get('AURORA_CONFIGURATION_LIMIT', '100'))
        entries = {}

        def add(name, entry):
            entries[name] = entry
            for special in sorted((entry.toplevel / 'specialisation').glob('*')):
                entries[f'{name}/{special.name}'] = Entry(special, entry.profile, entry.number)

        for profile in self.profiles():
            links = []
            for link in profile.parent.glob(glob.escape(profile.name) + '-*-link'):
                match = re.fullmatch(re.escape(profile.name) + r'-([0-9]+)-link', link.name)
                if match:
                    links.append((int(match[1]), link))
            for count, (number, link) in enumerate(sorted(links, reverse=True)):
                # install-grub.pl counts corrupt entries toward the limit too.
                if count >= limit:
                    break
                if (link / 'nixos-version').exists():
                    add(f'{profile.name}-{number}', Entry(link, profile, number))
        toplevel = self.env.get('AURORA_TOPLEVEL', '')
        if toplevel:
            installing = self.path(toplevel)
            if not any(os.path.realpath(e.toplevel) == os.path.realpath(installing) for e in entries.values()):
                add('the configuration being installed', Entry(installing))
        return entries

    def generations(self):
        if self._generations is not None:
            return self._generations
        entries = self.retained()
        declared = {name: read_generation(entry.toplevel / 'aurora-dtb-abi') for name, entry in entries.items()}
        kernels = {name: os.path.realpath(entry.toplevel / 'kernel') for name, entry in entries.items()}
        # A generation built before the declaration existed boots the same
        # kernel, device trees included, as any generation that shares its
        # store path, so it shares that kernel's generation.
        known = {}
        for name, value in declared.items():
            if value is not None:
                known.setdefault(kernels[name], []).append(value)
        self._generations = {name: value if value is not None else min(known.get(kernels[name], [1]))
                             for name, value in declared.items()}
        return self._generations

    # bootchain.Update's commit-time recheck asks for these.

    def kernel_images(self):
        return {name: entry.toplevel for name, entry in self.retained().items()}

    def generation(self, version):
        return self.generations()[version]

    def stage2_generation(self):
        directory = self.path(self.env['AURORA_STAGE2_DIR'])
        value = read_generation(directory / 'dtb-abi')
        return 0 if value is None else value

    def check_generations(self):
        selected = self.stage2_generation()
        self.selected_generation = selected
        entries = self.retained()
        older = [(name, value) for name, value in self.generations().items() if value < selected]
        if not older:
            return
        listing = ', '.join(f'{name} (generation {value})' for name, value in older)
        commands = []
        for profile in sorted({entries[name].profile for name, _ in older if entries[name].profile}):
            numbers = sorted({entries[name].number for name, _ in older if entries[name].profile == profile})
            commands.append(f'sudo nix-env --profile {profile} --delete-generations '
                            + ' '.join(map(str, numbers)))
        removal = (f'remove them with `{"; ".join(commands)}`' if commands
                   else 'install a configuration whose kernel declares it')
        raise Refused(f'this Stage 2 uses DT ABI generation {selected}, but GRUB still lists {listing}, '
                      'whose kernels need an older generation. Stage 2 and the boot menu are kept. '
                      f'After checking that a configuration you keep boots, {removal} '
                      'and run `sudo nixos-rebuild boot` again. No generation is removed automatically.')

    # The trial, as bootchain.Update stages it.

    def withdraw(self, digest):
        """Disarm this ESP's own untried candidate unless it is `digest`.

        Returns True when that candidate is already armed. 'armed' on the
        ESP means Stage 1 never spent the marker, so the candidate never
        booted, and its attempt record goes with it.
        """
        marker = self.path(self.env['ESP_ROOT']) / 'aura-try'
        if not marker.exists() and not marker.is_symlink():
            return False
        target, candidate, receipt, marker, relative = self.trial_paths()
        if self.marker(marker) != ('armed', relative):
            return False
        details = json.loads(receipt.read_text())
        if details.get('sha256') == digest:
            return True
        marker.unlink()
        bootchain.sync_dir(marker.parent)
        self.flush_esp()
        self.validate_version(details['kernel'])
        (self.path('/var/lib/aurora-stage2/attempts') / details['kernel']).unlink(missing_ok=True)
        candidate.unlink(missing_ok=True)
        receipt.unlink(missing_ok=True)
        bootchain.sync_dir(target.parent)
        print(f'Withdrew the untried Stage 2 trial {relative}: this install selects another image')
        return False

    def stage_trial(self, selected, payload):
        if self.withdraw(selected):
            print(f'Stage 2 trial {selected} is already armed')
            return
        super().stage_trial(selected, payload)

    def replace(self, target, previous, payload):
        """bootchain.Update.apply's direct replacement, for Stage 1 without aura-try."""
        fd, name = tempfile.mkstemp(prefix=f'.{target.name}.', dir=target.parent)
        staged = Path(name)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fchmod(stream.fileno(), 0o644)
                os.fsync(stream.fileno())
            if staged.read_bytes() != payload:
                raise Refused('the copy written to the ESP does not verify')
            if previous is not None:
                bootchain.replace_file(target.with_name(target.name + '.old'), previous)
            os.replace(staged, target)
            bootchain.sync_dir(target.parent)
        finally:
            staged.unlink(missing_ok=True)
        print(f'Stage 2 updated at {target}; the previous one is m1n1/{target.name}.old')

    # Entry points.

    def selected_source(self):
        """The Stage 2 file this Mac takes from the build, as install-stage2.sh selects it."""
        directory = self.path(self.env['AURORA_STAGE2_DIR'])
        board = self.ctxr_board()
        if board:
            return directory / 'ctxr' / f'boot-ctxr-{board.removeprefix("apple,")}.bin', 'boot-ctxr.bin'
        return directory / 'boot.bin', 'boot.bin'

    def check(self):
        """Before a switch: refuse a Stage 2 change the listed generations cannot boot."""
        source, name = self.selected_source()
        if not source.is_file():
            return  # The installer only warns; nothing is written.
        target = self.path(self.env.get('ESP_ROOT', '/boot/efi')) / 'm1n1' / name
        payload = source.read_bytes()
        try:
            # The bytes install would write; a signing failure is install's to report.
            payload = self.sign(payload)
        except Refused:
            pass
        try:
            if target.read_bytes() == payload:
                return
        except OSError:
            pass
        self.check_generations()

    def install(self):
        payload = self.path(self.env['AURORA_STAGE2_SOURCE']).read_bytes()
        if hashlib.sha256(payload).hexdigest() != self.env.get('AURORA_STAGE2_SHA256'):
            raise Refused('the Stage 2 input does not match its digest')
        # The built image as aurora-secboot's stage2 hook returns it: signed with the owner's
        # Stage 2 key when signing is on (AURORA_STAGE2_SIGNER), else unchanged. The signature is
        # deterministic, so reinstalling the same image with the same key writes nothing.
        payload = self.sign(payload)
        digest = hashlib.sha256(payload).hexdigest()
        target = self.target()
        if target.is_symlink():
            raise Refused('Stage 2 target is a symlink')
        previous = target.read_bytes() if target.exists() else None
        if previous == payload:
            # Back to the live image: a newer candidate must not boot instead.
            self.withdraw(digest)
            return
        self.check_generations()
        if previous is not None and self.supports_trial():
            self.stage_trial(digest, payload)
        else:
            self.replace(target, previous, payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=('install', 'check', 'commit', 'guard'))
    args = parser.parse_args(argv)
    env = dict(os.environ)
    if env.get('AURORA_STAGE2_DIR'):
        env.setdefault('AURORA_MONITOR_FREE_MARKER', env['AURORA_STAGE2_DIR'] + '/monitor-free')
        env.setdefault('M1N1', env['AURORA_STAGE2_DIR'] + '/aura.bin')
    kept = {
        'install': 'the ESP Stage 2 was left unchanged',
        'check': 'the boot menu and Stage 2 were left unchanged',
        'commit': 'the live Stage 2 and the trial evidence were kept',
        'guard': 'the trial was left as it is',
    }[args.mode]
    try:
        # One lock for bootloader installs and the boot-time services.
        lock = Path(env.get('AURORA_STAGE2_LOCK', '/run/lock/aurora-stage2.lock'))
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            update = NixosUpdate(Path(env.get('AURORA_STAGE2_ROOT', '/')), env)
            getattr(update, args.mode)()
    except (Refused, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f'aurora-stage2 {args.mode}: {error}; {kept}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
