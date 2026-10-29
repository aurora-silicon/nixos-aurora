#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check the finished installer root's Aurora payloads and early sequencer."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess

spec = importlib.util.spec_from_file_location('basics', Path(__file__).with_name('check-basics.py'))
basics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(basics)


def cpio_names(stream):
    """Read newc archives without extracting or holding the initrd in memory."""
    def discard(size):
        while size:
            block = stream.read(min(size, 1024 * 1024))
            if not block:
                raise ValueError('truncated initrd')
            size -= len(block)
    while True:
        # Newc archives may have zero padding or another concatenated archive.
        first = stream.read(1)
        while first == b'\0':
            first = stream.read(1)
        if not first:
            return
        header = first + stream.read(109)
        if len(header) != 110 or header[:6] not in (b'070701', b'070702'):
            raise ValueError('invalid newc initrd header')
        fields = [int(header[start:start + 8], 16) for start in range(6, 110, 8)]
        size, namesize = fields[6], fields[11]
        if not 0 < namesize <= 4096:
            raise ValueError('invalid initrd filename length')
        name = stream.read(namesize)
        if len(name) != namesize or name[-1:] != b'\0':
            raise ValueError('truncated initrd filename')
        discard(-(110 + namesize) % 4)
        yield name[:-1].decode()
        discard(size)
        discard(-size % 4)


def check_initrd(path):
    with path.open('rb') as stream:
        magic = stream.read(6)
    tool = next((tool for prefix, tool in ((b'\x28\xb5\x2f\xfd', 'zstd'), (b'\x1f\x8b', 'gzip'),
                 (b'\xfd7zXZ\x00', 'xz'), (b'\x04\x22\x4d\x18', 'lz4')) if magic.startswith(prefix)), None)
    if tool:
        with subprocess.Popen([tool, '-dc', str(path)], stdout=subprocess.PIPE) as process:
            names = list(cpio_names(process.stdout))
            if process.wait() != 0:
                raise ValueError('initrd decompression failed')
    else:
        with path.open('rb') as stream:
            names = list(cpio_names(stream))
    if not any(re.search(r'(^|/)snd-seq\.ko(?:\.(?:xz|gz|zst))?$', name) for name in names):
        raise ValueError('the image initrd does not carry snd-seq')


def check(root):
    data = json.loads(root.text(f'{root.etc}/aurora/parity.json') or '{}')
    defaults = data.get('defaults', {})
    required = {'skipLockedControls', 'initrdSequencer', 'malcontentSignal', 'flatpakGL', 'fexMesa'}
    if data.get('schema') != 1 or set(defaults) != required or not all(value is True for value in defaults.values()):
        raise ValueError('the image does not enable every Aurora parity default')
    for key, file, commit in (
            ('kernel', 'aurora-source-commit', data['kernelCommit']),
            ('mesa', '.aurora-mesa-commit', data['mesaCommit']),
            ('fexMesa', '.aurora-mesa-commit', data['mesaCommit']),
            ('flatpakGL', 'aurora-mesa-commit.25.08', data['mesaCommit']),
            ('flatpakGL', 'aurora-mesa-commit.26.08', data['mesaCommit'])):
        if (root.text(f'{data[key]}/{file}') or '').strip() != commit:
            raise ValueError(f'{key}/{file}: missing or stale image payload')
    for arch in ('lib64', 'lib'):
        if not root.path(f'{data["fexMesa"]}/usr/{arch}/libvulkan_asahi.so').is_file():
            raise ValueError(f'FEX Mesa {arch} is missing')
    for branch in ('25.08', '26.08'):
        if not root.path(f'{data["flatpakGL"]}/refs/heads/runtime/org.freedesktop.Platform.GL.aurora/aarch64/{branch}').is_file():
            raise ValueError(f'Flatpak GL {branch} is missing')
    for variant in ('v2-t0', 'v3-t0', 'v3-t1', 'v4-t0', 'v5-t0', 'v5-t1'):
        if not root.path(f'{data["avdFirmware"]}/lib/firmware/apple/avd-fw-{variant}.bin').is_file():
            raise ValueError(f'AVD firmware {variant} is missing')
    check_initrd(root.path(f'{root.system}/initrd'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--system', required=True)
    args = parser.parse_args()
    check(basics.Root(args.root, args.system))
    print('aurora parity: image payloads and initrd: ok')
