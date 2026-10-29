#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install or remove the system Aurora GL extension and its owned overrides."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess

spec = importlib.util.spec_from_file_location('repository', Path(__file__).with_name('validate-repository.py'))
repository = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repository)

REMOTE = 'aurora-gl'
GL = '/usr/lib/aarch64-linux-gnu/GL'
ENV = {
    'VK_DRIVER_FILES': f'{GL}/vulkan/icd.d/asahi_icd.aarch64.json:{GL}/vulkan/icd.d/lvp_icd.aarch64.json',
    '__EGL_VENDOR_LIBRARY_FILENAMES': f'{GL}/glvnd/egl_vendor.d/50_mesa.json',
    'LIBGL_DRIVERS_PATH': f'{GL}/lib/dri',
}


def flatpak(*args):
    return subprocess.check_output(['flatpak', '--system', *args], text=True)


def remotes():
    return dict(line.split('\t', 1) for line in flatpak('remotes', '--columns=name,url').splitlines())


def enable(repo, commit):
    # Validate both complete branches before making any host changes.
    repository.validate(repo, commit)
    url = Path(repo).as_uri()
    if REMOTE in remotes():
        flatpak('remote-modify', '--no-gpg-verify', '--url=' + url, REMOTE)
    else:
        flatpak('remote-add', '--no-gpg-verify', '--no-enumerate', '--no-use-for-deps',
                '--title=Aurora Mesa (local)', REMOTE, url)
    for branch in repository.BRANCHES:
        ref = f'runtime/{repository.ID}/aarch64/{branch}'
        flatpak('install', '--noninteractive', '-y', '--no-deps', '--no-related', '--or-update', REMOTE, ref)
        flatpak('pin', ref)
    flatpak('override', *(f'--env={key}={value}' for key, value in ENV.items()))


def remove_owned_overrides(path):
    """Keep keys changed by an administrator, including other environments."""
    path = Path(path)
    if not path.is_file():
        return
    lines = path.read_text().splitlines(keepends=True)
    section = None
    kept = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('['):
            section = stripped
        if section == '[Environment]' and stripped in {f'{key}={value}' for key, value in ENV.items()}:
            continue
        kept.append(line)
    if not any(line.strip() and not line.lstrip().startswith(('[', '#', ';')) for line in kept):
        path.unlink()
    else:
        temporary = path.with_name(path.name + '.aurora-new')
        temporary.write_text(''.join(kept))
        os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)


def disable(repo):
    remove_owned_overrides('/var/lib/flatpak/overrides/global')
    for line in flatpak('list', '--runtime', '--columns=ref,origin').splitlines():
        ref, _, origin = line.partition('\t')
        if ref.startswith(repository.ID + '/aarch64/') and origin == REMOTE:
            flatpak('pin', '--remove', 'runtime/' + ref)
            flatpak('uninstall', '--noninteractive', '-y', 'runtime/' + ref)
    # An administrator's replacement remote is left in place.
    if remotes().get(REMOTE) == Path(repo).as_uri():
        flatpak('remote-delete', REMOTE)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['enable', 'disable'])
    parser.add_argument('--repo', required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    if args.action == 'enable':
        enable(args.repo, args.commit)
    else:
        disable(args.repo)
