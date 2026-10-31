#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate complete committed GL extensions before packaging or installation.

Payload checks adapted from aurora-silicon/fedora-aurora at 71a189f2ea45.
"""
import argparse
import configparser
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile

BRANCHES = ('25.08', '26.08')
ID = 'org.freedesktop.Platform.GL.aurora'


def validate_payload(root, commit):
    root = Path(root).resolve()
    if (root / '.aurora-mesa-commit').read_text().strip() != commit:
        raise ValueError('GL payload has the wrong Mesa commit')
    for name in ('lib/libvulkan_asahi.so', 'lib/libvulkan_lvp.so',
                 'lib/libEGL_mesa.so.0', 'lib/libGLX_mesa.so.0',
                 'lib/libLLVM.so.22.1', 'lib/dri/asahi_dri.so',
                 'lib/dri/zink_dri.so', 'lib/dri/swrast_dri.so'):
        path = (root / name).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError(f'{name}: symlink escapes the payload')
        with path.open('rb') as stream:
            header = stream.read(20)
        if len(header) != 20 or header[:6] != b'\x7fELF\x02\x01' or struct.unpack('<H', header[18:20])[0] != 183:
            raise ValueError(f'{name}: not an AArch64 ELF library')
    for name, expected_library in (
            ('vulkan/icd.d/asahi_icd.aarch64.json', 'libvulkan_asahi.so'),
            ('vulkan/icd.d/lvp_icd.aarch64.json', 'libvulkan_lvp.so'),
            ('glvnd/egl_vendor.d/50_mesa.json', 'libEGL_mesa.so.0')):
        data = json.loads((root / name).read_text())['ICD']
        library = data['library_path'].removeprefix('/usr/lib/aarch64-linux-gnu/GL/aurora/')
        # The loader can also use the basename with the extension's library path.
        path = root / (library if '/' in library else 'lib/' + library)
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError(f'{name}: library_path is absent from the payload')
        if path.resolve() != (root / 'lib' / expected_library).resolve(strict=True):
            raise ValueError(f'{name}: library_path selects the wrong driver')
    defaults = (root / 'share/drirc.d/00-hk-defaults.conf').read_text()
    if 'hk_report_honeykrisp_driver_id' not in defaults:
        raise ValueError('GL payload lacks the DXVK/vkd3d driver-ID defaults')
    blob = (root / 'lib/libvulkan_asahi.so').read_bytes()
    expected = f'(git-{commit[:10]}), Borealis'.encode()
    if expected not in blob:
        raise ValueError('GL driverInfo lacks the pinned commit and Borealis name')



def validate(repo, commit, checkout=None):
    repo = Path(repo).resolve()
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('expected a full Mesa commit')
    if checkout is None:
        def checkout(ref, tree):
            subprocess.run(['ostree', f'--repo={repo}', 'checkout', '--user-mode',
                            ref, str(tree)], check=True)
    for branch in BRANCHES:
        if (repo / f'aurora-mesa-commit.{branch}').read_text().strip() != commit:
            raise ValueError(f'{branch}: stale repository Mesa stamp')
        ref = f'runtime/{ID}/aarch64/{branch}'
        with tempfile.TemporaryDirectory(prefix='aurora-gl-check-') as tmp:
            tree = Path(tmp) / 'tree'
            checkout(ref, tree)
            metadata = configparser.ConfigParser(interpolation=None)
            metadata.read_string((tree / 'metadata').read_text())
            if (metadata.get('Runtime', 'name') != ID
                    or metadata.get('ExtensionOf', 'ref') != f'runtime/org.freedesktop.Platform/aarch64/{branch}'
                    or metadata.getint('ExtensionOf', 'priority') != 10):
                raise ValueError(f'{branch}: wrong GL extension identity or priority')
            validate_payload(tree / 'files', commit)
        print(f'{ref}: complete AArch64 GL payload, Mesa {commit}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    validate(args.repo, args.commit)
