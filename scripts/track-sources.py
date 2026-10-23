#!/usr/bin/env python3
"""Propose NixOS source-pin updates for tracked upstream branches.

`plan` is read-only with respect to GitHub: it writes a patch and a result
record under --output. `open-pr`, `merge` and `mirror` act on GitHub with the
workflow token. sources.json carries the fetchurl hash in SRI form
(`nix_hash`), computed from the same verified archive bytes as `sha256`.
See docs/updates.md.
"""
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import trackerlib as tl  # noqa: E402
import updatelib as lib  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NIX = True
# Source key -> the flake package the CI matrix builds.
RECIPES = {'kernel-aurora': 'kernel', 'aura': 'aura', 'mesa-aurora': 'mesa'}
KINDS = {'kernel-aurora': 'kernel', 'mesa-aurora': 'mesa'}
CI_WORKFLOWS = ['checks.yml']
PATCH_PATHS = [r'sources\.json', r'kernel/provenance\.json', r'locks/aura\.Cargo\.lock', r'overlay\.nix',
               r'mesa\.nix']
# Files that record a source commit outside sources.json.
COMMIT_FILES = {'kernel-aurora': ['kernel/provenance.json'], 'aura': [], 'mesa-aurora': []}
# Where each Rust source's lock comes from inside its archive.
CARGO_LOCKS = {'aura': ('rust/Cargo.lock', 'locks/aura.Cargo.lock')}


def set_nix_version(path, old, new, keys):
    text = path.read_text()
    updated = text
    for key in keys:
        updated = re.sub(rf'(\b{key}\s*=\s*)"{re.escape(old)}";', rf'\g<1>"{new}";', updated)
    if updated == text:
        return False
    path.write_text(updated)
    return True


def update_recipe(root, item, today):
    key = item['key']
    notes = []
    for name in COMMIT_FILES[key]:
        path = root / name
        path.write_text(tl.replace_commit(path.read_text(), item['old'], item['new']))
    if key in CARGO_LOCKS:
        inner, target = CARGO_LOCKS[key]
        found = lib.read_members(item['archive_path'], [inner])
        if inner not in found:
            item.setdefault('needs_review', []).append(f'the archive has no {inner}')
        else:
            new_lock = found[inner].decode()
            old_lock = (root / target).read_text()
            if new_lock != old_lock:
                (root / target).write_text(new_lock)
                notes.append(f'{target} updated from the archive')
                if tl.cargo_git_sources(new_lock) != tl.cargo_git_sources(old_lock):
                    item.setdefault('needs_review', []).append(
                        'git dependencies changed; update importCargoLock outputHashes in overlay.nix')
    old_version = item.get('previous_version')
    if item.get('version_changed') and old_version:
        if key == 'kernel-aurora':
            changed = set_nix_version(root / 'overlay.nix', old_version, item['version'],
                                      ['version', 'modDirVersion'])
            branch = '.'.join(item['version'].split('.')[:2])
            text = (root / 'overlay.nix').read_text()
            (root / 'overlay.nix').write_text(re.sub(r'(extraMeta\.branch\s*=\s*)"[^"]*";',
                                                     rf'\g<1>"{branch}";', text, count=1))
        else:
            changed = set_nix_version(root / 'mesa.nix', old_version, item['version'], ['version'])
        notes.append(f'version {old_version} -> {item["version"]}'
                     + ('' if changed else ' (recipe version not found; edit it by hand)'))
        if not changed:
            item.setdefault('needs_review', []).append('the recipe version could not be updated')
    return notes


def extra_archives():
    """The bindgen archive is pinned in bindgen/sources.json; mirror it too."""
    import json
    manifest = json.loads((ROOT / 'bindgen/sources.json').read_text())
    return {f'rust-bindgen-{manifest["version"]}.tar.gz': (manifest['source_url'], manifest['source_sha256'])}


def run_checks(root):
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], cwd=root, check=True)


def ci_inputs(packages):
    return {'checks.yml': {'packages': ' '.join(packages)}}


if __name__ == '__main__':
    tl.main(sys.modules[__name__])
