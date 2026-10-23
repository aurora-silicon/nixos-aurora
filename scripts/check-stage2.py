#!/usr/bin/env python3
"""Check a combined ESP Stage 2 image before it can reach an ESP.

The layout is the one asahi-scripts' update-m1n1 writes on ALARM and Fedora
and the Apple Silicon NixOS module builds: the aura ESP Stage 2 binary,
every Apple device tree of one kernel, U-Boot as one gzip member, then
optional m1n1 option lines (chosen.*, display=, mitigations=). One image
serves every Mac, so the device trees of required boards (the MacBook Neo
by default) must be present. Prints a JSON manifest; exits non-zero on any
deviation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import zlib

DTB_MAGIC = b'\xd0\x0d\xfe\xed'
OPTION = re.compile(rb'(chosen\.[A-Za-z0-9_.,-]+=[ -~]*|display=[ -~]*|mitigations=[ -~]*)')
MAX_BYTES = 64 * 1024 * 1024


def root_compatible(blob):
    fields = struct.unpack_from('>10I', blob)
    magic, total, struct_offset, strings_offset = fields[:4]
    strings_size, struct_size = fields[8], fields[9]
    if (magic != 0xD00DFEED or total != len(blob)
            or struct_offset + struct_size > total or strings_offset + strings_size > total):
        raise ValueError('invalid device tree header')
    strings = blob[strings_offset:strings_offset + strings_size]
    cursor, end = struct_offset, struct_offset + struct_size
    if struct.unpack_from('>I', blob, cursor)[0] != 1:
        raise ValueError('device tree has no root node')
    cursor += 4
    name_end = blob.find(b'\0', cursor, end)
    if name_end < 0 or blob[cursor:name_end]:
        raise ValueError('invalid device tree root name')
    cursor = (name_end + 4) & ~3
    while cursor + 4 <= end:
        token = struct.unpack_from('>I', blob, cursor)[0]
        cursor += 4
        if token == 4:
            continue
        if token != 3 or cursor + 8 > end:
            break
        size, name_offset = struct.unpack_from('>II', blob, cursor)
        cursor += 8
        name = strings[name_offset:strings.find(b'\0', name_offset)]
        value = blob[cursor:cursor + size]
        cursor = (cursor + size + 3) & ~3
        if name == b'compatible':
            return value.split(b'\0', 1)[0].decode('ascii', 'replace')
    raise ValueError('device tree root has no compatible')


def check(stage2, aura, required=()):
    if not 0 < len(stage2) <= MAX_BYTES:
        raise ValueError('Stage 2 size is out of range')
    if not aura or not stage2.startswith(aura):
        raise ValueError('Stage 2 does not start with the aura build')
    cursor = len(aura)
    boards = []
    while stage2[cursor:cursor + 4] == DTB_MAGIC:
        if cursor + 40 > len(stage2):
            raise ValueError('truncated device tree')
        length = struct.unpack_from('>I', stage2, cursor + 4)[0]
        if length < 40 or cursor + length > len(stage2):
            raise ValueError('invalid device tree length')
        boards.append(root_compatible(stage2[cursor:cursor + length]))
        cursor += length
    if not boards:
        raise ValueError('Stage 2 carries no device trees')
    if stage2[cursor:cursor + 3] != b'\x1f\x8b\x08':
        raise ValueError('U-Boot is not one gzip member after the device trees')
    inflater = zlib.decompressobj(wbits=31)
    uboot = inflater.decompress(stage2[cursor:])
    if not inflater.eof or not uboot:
        raise ValueError('U-Boot does not decompress')
    trailer = inflater.unused_data
    options = [line for line in trailer.split(b'\n') if line]
    if any(not OPTION.fullmatch(line) for line in options):
        raise ValueError('unexpected data after U-Boot')
    missing = [board for board in required if f'apple,{board}' not in boards]
    if missing:
        raise ValueError('Stage 2 lacks device trees for ' + ', '.join(missing))
    return {
        'schema': 1,
        'bytes': len(stage2),
        'sha256': hashlib.sha256(stage2).hexdigest(),
        'auraSha256': hashlib.sha256(aura).hexdigest(),
        'deviceTrees': len(boards),
        'boards': sorted(set(boards)),
        'ubootBytes': len(uboot),
        'options': [line.decode() for line in options],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--stage2', type=Path, required=True)
    parser.add_argument('--aura', type=Path, required=True)
    parser.add_argument('--require-board', action='append', default=[],
                        help='a board (e.g. j700) whose device tree must be present')
    args = parser.parse_args()
    try:
        manifest = check(args.stage2.read_bytes(), args.aura.read_bytes(), args.require_board)
    except (OSError, ValueError, struct.error, zlib.error) as error:
        sys.exit(f'Stage 2 check failed: {error}')
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
