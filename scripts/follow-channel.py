#!/usr/bin/env python3
"""Point an image's /etc/nixos flake at an Aurora update channel.

The image builder first locks flake.nix against the exact commit the image
was built from. This rewrites the `aurora` input to follow the channel ref
(`channel-testing` or `channel-stable`) and records that ref as the lock's
`original` while leaving the locked commit untouched, so:

- the first rebuild uses exactly the image's commit, offline from GitHub's
  point of view (the lock already names it);
- `nix flake update` (or `aurora-update`) moves to the channel's newest
  commit, which the deploy and promotion workflows move only after the signed
  cache holds its outputs.

`pinned` keeps the exact-commit input. It also writes /etc/nixos/README.
"""
import json
from pathlib import Path
import re
import sys

OWNER, REPO = 'aurora-silicon', 'nixos-aurora'


def follow(directory, revision, channel):
    if not re.fullmatch(r'[0-9a-f]{40}', revision) or channel not in ('pinned', 'testing', 'stable'):
        raise ValueError('expected a full commit and pinned, testing or stable')
    directory = Path(directory)
    flake = directory / 'flake.nix'
    lock_path = directory / 'flake.lock'
    lock = json.loads(lock_path.read_text())
    name = lock['nodes'][lock['root']]['inputs']['aurora']
    node = lock['nodes'][name]
    locked = node['locked']
    if (locked.get('type'), locked.get('owner'), locked.get('repo'), locked.get('rev')) != ('github', OWNER, REPO, revision):
        raise ValueError(f'the lock does not pin {OWNER}/{REPO} at {revision}')
    if channel != 'pinned':
        ref = f'channel-{channel}'
        text = flake.read_text()
        old = f'"github:{OWNER}/{REPO}/{revision}"'
        if text.count(old) != 1:
            raise ValueError('flake.nix does not name the image commit exactly once')
        flake.write_text(text.replace(old, f'"github:{OWNER}/{REPO}/{ref}"'))
        node['original'] = {'owner': OWNER, 'ref': ref, 'repo': REPO, 'type': 'github'}
        lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + '\n')
        follows = (f'It follows the Aurora {channel} channel (the {ref} branch of {OWNER}/{REPO}), which '
                   'moves only when the signed binary cache holds its outputs. To take the newest update: '
                   'sudo aurora-update (the same as sudo nix flake update aurora --flake /etc/nixos, then '
                   'sudo nixos-rebuild switch --flake /etc/nixos#aurora).')
    else:
        follows = (f'It is pinned to {OWNER}/{REPO} at {revision}; edit the aurora input in flake.nix '
                   f'to github:{OWNER}/{REPO}/channel-testing to receive updates.')
    (directory / 'README').write_text(
        'Run sudo nixos-rebuild switch --flake /etc/nixos#aurora to rebuild this machine. The aurora output '
        'stays available when the hostname changes. machine.nix preserves its filesystem identities; owner.nix '
        'is written by firstboot. The password hash remains outside the Nix store.\n\n'
        f'flake.lock pins the commit this system was installed from ({revision}). {follows} Every rebuild '
        'refreshes the Stage 2 boot file on the EFI partition and keeps the previous one as '
        'm1n1/boot.bin.old. Nothing updates unattended.\n')


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('usage: follow-channel.py ETC_NIXOS COMMIT pinned|testing|stable')
    follow(*sys.argv[1:])
