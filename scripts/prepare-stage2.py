#!/usr/bin/env python3
"""Split a current combined boot image into board-sized Stage 2 payloads."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct


def digest(data):
    return hashlib.sha256(data).hexdigest()


def root_compatible(blob):
    if len(blob) < 40:
        raise ValueError('short device tree')
    fields = struct.unpack_from('>10I', blob)
    magic, total, struct_offset, strings_offset = fields[:4]
    struct_size, strings_size = fields[9], fields[8]
    if (magic != 0xD00DFEED or total != len(blob) or
            struct_offset + struct_size > total or strings_offset + strings_size > total):
        raise ValueError('invalid device tree header')
    strings = blob[strings_offset:strings_offset + strings_size]
    end = struct_offset + struct_size
    cursor = struct_offset
    if struct.unpack_from('>I', blob, cursor)[0] != 1:
        raise ValueError('missing device tree root')
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
        if token != 3:
            break
        if cursor + 8 > end:
            break
        size, name_offset = struct.unpack_from('>II', blob, cursor)
        cursor += 8
        name_end = strings.find(b'\0', name_offset)
        if name_end < 0 or cursor + size > end:
            raise ValueError('invalid device tree property')
        name = strings[name_offset:name_end]
        value = blob[cursor:cursor + size]
        cursor = (cursor + size + 3) & ~3
        if name == b'compatible':
            first = value.split(b'\0', 1)[0]
            if not re.fullmatch(rb'apple,j[0-9]+[a-z]*', first):
                return None
            return first.decode('ascii').removeprefix('apple,')
    raise ValueError('missing root compatible')


def prepare(combined_path, aura_path, output):
    combined = combined_path.read_bytes()
    aura = aura_path.read_bytes()
    if not aura or not combined.startswith(aura):
        raise ValueError('combined image does not start with the current Aura build')
    cursor = len(aura)
    boards = {}
    count = 0
    while combined[cursor:cursor + 4] == b'\xd0\x0d\xfe\xed':
        if cursor + 8 > len(combined):
            raise ValueError('truncated device tree')
        length = struct.unpack_from('>I', combined, cursor + 4)[0]
        if length < 40 or cursor + length > len(combined):
            raise ValueError('invalid device tree length')
        blob = combined[cursor:cursor + length]
        board = root_compatible(blob)
        if board is not None:
            boards.setdefault(board, []).append(blob)
        cursor += length
        count += 1
    trailer = combined[cursor:]
    if count == 0 or not boards or not trailer.startswith(b'\x1f\x8b\x08'):
        raise ValueError('missing device trees or compressed next stage')
    gzip.decompress(trailer)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.glob('boot-*.bin')):
        raise ValueError('board payload output already exists')
    records = {}
    for board, trees in sorted(boards.items()):
        data = aura + b''.join(trees) + trailer
        name = f'boot-{board}.bin'
        (output / name).write_bytes(data)
        records[board + 'ap'] = {
            'member': 'esp/m1n1/' + name,
            'bytes': len(data),
            'sha256': digest(data),
            'deviceTrees': len(trees),
        }
    return {
        'schema': 1,
        'sourceSha256': digest(combined),
        'auraSha256': digest(aura),
        'nextStageSha256': digest(trailer),
        'deviceTreeCount': count,
        'boards': records,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--combined', required=True, type=Path)
    parser.add_argument('--aura', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    args = parser.parse_args()
    manifest = prepare(args.combined, args.aura, args.output)
    args.manifest.write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    print(f"prepared {len(manifest['boards'])} board payloads from {manifest['deviceTreeCount']} trees")
