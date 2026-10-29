#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reject absent or stale Aurora GL branches before packaging or installation."""
import argparse
import configparser
from pathlib import Path
import re
import subprocess

BRANCHES = ('25.08', '26.08')
ID = 'org.freedesktop.Platform.GL.aurora'


def validate(repo, commit, read=None):
    repo = Path(repo)
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('expected a full Mesa commit')
    if read is None:
        def read(ref, path):
            return subprocess.check_output(['ostree', f'--repo={repo}', 'cat', ref, path], text=True)
    for branch in BRANCHES:
        stamp = repo / f'aurora-mesa-commit.{branch}'
        if stamp.read_text().strip() != commit:
            raise ValueError(f'{branch}: stale repository Mesa stamp')
        ref = f'runtime/{ID}/aarch64/{branch}'
        if read(ref, '/files/.aurora-mesa-commit').strip() != commit:
            raise ValueError(f'{branch}: stale Mesa payload')
        metadata = configparser.ConfigParser(interpolation=None)
        metadata.read_string(read(ref, '/metadata'))
        if (metadata.get('Runtime', 'name') != ID
                or metadata.get('ExtensionOf', 'ref') != f'runtime/org.freedesktop.Platform/aarch64/{branch}'
                or metadata.getint('ExtensionOf', 'priority') != 10):
            raise ValueError(f'{branch}: wrong GL extension identity or priority')
        for file in ('vulkan/icd.d/asahi_icd.aarch64.json', 'vulkan/icd.d/lvp_icd.aarch64.json',
                     'glvnd/egl_vendor.d/50_mesa.json'):
            if not read(ref, '/files/' + file).strip():
                raise ValueError(f'{branch}: missing driver manifest {file}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    validate(args.repo, args.commit)
