#!/usr/bin/env python3
"""Split a current combined boot image into board-sized Stage 2 payloads."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


# Also works when loaded by a test rather than executed as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage2 import parse  # noqa: E402


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare(combined_path, aura_path, output):
    combined = combined_path.read_bytes()
    aura = aura_path.read_bytes()
    parsed = parse(combined, aura)
    boards = {}
    for compatible, blob in parsed['trees']:
        if re.fullmatch(r'apple,j[0-9]+[a-z]*', compatible):
            board = compatible.removeprefix('apple,')
            boards.setdefault(board, []).append(blob)
    if not boards:
        raise ValueError('missing board device trees')
    trailer = parsed['trailer']
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
        'deviceTreeCount': len(parsed['trees']),
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
