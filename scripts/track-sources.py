#!/usr/bin/env python3
"""Propose NixOS source-pin updates for tracked upstream branches.

`plan` is read-only with respect to GitHub: it writes a patch and a result
record under --output. `open-pr`, `merge` and `mirror` act on GitHub with the
workflow token. sources.json carries the fetchurl hash in SRI form
(`nix_hash`), computed from the same verified archive bytes as `sha256`.
See docs/updates.md.
"""
from pathlib import Path
import configparser
import os
import json
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import trackerlib as tl  # noqa: E402
import updatelib as lib  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NIX = True
# Source key -> the flake package the CI matrix builds.
RECIPES = {'kernel-aurora': 'kernel', 'aura': 'aura', 'mesa-aurora': 'mesa',
           'fex-emu': 'fex', 'aurora-steam-native': 'steam'}
KINDS = {'kernel-aurora': 'kernel', 'mesa-aurora': 'mesa'}
CI_WORKFLOWS = ['checks.yml']
PATCH_PATHS = [r'sources\.json', r'kernel/provenance\.json', r'locks/aura\.Cargo\.lock']
# Files that record a source commit outside sources.json.
COMMIT_FILES = {'kernel-aurora': ['kernel/provenance.json'], 'aura': [], 'mesa-aurora': [],
                'fex-emu': [], 'aurora-steam-native': []}
# Where each Rust source's lock comes from inside its archive.
CARGO_LOCKS = {'aura': ('rust/Cargo.lock', 'locks/aura.Cargo.lock')}


def refresh_fex_submodules(root, item):
    """Resolve the selected gitlinks before admitting a new FEX parent pin."""
    path = root / 'sources.json'
    pins = json.loads(path.read_text())
    parent = pins['fex-emu']
    slug = lib.repository_slug(parent['repository'])
    tree = lib.gh_api(f'repos/{slug}/git/trees/{item["new"]}?recursive=1')
    if tree.get('truncated'):
        raise ValueError('FEX git tree response was truncated')
    gitlinks = {entry['path']: entry['sha'] for entry in tree['tree']
                if entry.get('mode') == '160000' and entry.get('type') == 'commit'}
    modules = configparser.ConfigParser(interpolation=None)
    modules.read_string(lib.read_members(item['archive_path'], ['.gitmodules'])['.gitmodules'].decode())
    repositories = {modules[section]['path']: modules[section]['url'] for section in modules.sections()}
    refreshed = {}
    notes = []
    for name, old in parent['extra_sources'].items():
        source_path = old['path']
        commit = gitlinks[source_path]
        if not lib.HEX40.fullmatch(commit):
            raise ValueError(f'{name}: invalid gitlink commit')
        repository = lib.repository_slug(repositories[source_path])
        if repository != lib.repository_slug(old['repository']):
            raise ValueError(f'{name}: submodule repository changed; review it explicitly')
        pin = dict(old)
        if commit != old['commit']:
            submodule = {'key': name, 'repository': repository, 'new': commit}
            info = tl.prepare_source(submodule, Path(item['archive_path']).parent,
                                     os.environ.get('GITHUB_REPOSITORY', 'aurora-silicon/nixos-aurora'),
                                     token=os.environ.get('GH_TOKEN'))
            pin.update(commit=commit, source_url=info['source_url'], archive_root=info['archive_root'],
                       sha256=info['sha256'], nix_hash=info['nix_hash'])
            if not info['tree_verified']:
                item.setdefault('needs_review', []).append(f'{name}: {info.get("tree_note", "archive tree mismatch")}')
            notes.append(f'FEX {name}: {old["commit"][:12]} -> {commit[:12]}')
        refreshed[name] = pin
    parent.update(extra_sources=refreshed, submodules_commit=item['new'])
    path.write_text(json.dumps(pins, indent=2) + '\n')
    return notes


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
                        'git dependencies changed; update importCargoLock outputHashes in pkgs/aura.nix')
    if key == 'fex-emu':
        try:
            notes.extend(refresh_fex_submodules(root, item))
        except (OSError, ValueError, RuntimeError, KeyError, configparser.Error) as error:
            # The recipe refuses a parent whose gitlinks were not refreshed.
            item.setdefault('needs_review', []).append(f'FEX submodule refresh failed: {error}')
    if key == 'aura':
        # A release label belongs to the commit it was tagged on, not to the next one.
        path = root / 'sources.json'
        pins = json.loads(path.read_text())
        if pins['aura'].pop('release_tag', None) is not None:
            path.write_text(json.dumps(pins, indent=2) + '\n')
    if item.get('version_changed') and item.get('previous_version'):
        notes.append(f'version {item["previous_version"]} -> {item["version"]}')
    return notes


def extra_archives():
    """The bindgen archive is pinned in bindgen/sources.json; mirror it too."""
    import json
    manifest = json.loads((ROOT / 'bindgen/sources.json').read_text())
    return {f'rust-bindgen-{manifest["version"]}.tar.gz': (manifest['source_url'], manifest['source_sha256'])}


def run_checks(root):
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], cwd=root, check=True)


def ci_inputs(packages):
    packages = set(packages)
    if 'mesa' in packages:
        # All graphics outputs consume the same pin. A tracker change
        # must build the runtime payloads too, even with an explicit matrix.
        packages.update(('fex-mesa', 'flatpak-gl', 'rusticl', 'lavapipe', 'graphics'))
    return {'checks.yml': {'packages': ' '.join(sorted(packages))}}


if __name__ == '__main__':
    tl.main(sys.modules[__name__])
