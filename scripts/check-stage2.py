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
import sys

# Also works when loaded by a test rather than executed as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage2 import parse  # noqa: E402


def check(stage2, aura, required=()):
    parsed = parse(stage2, aura)
    boards = [compatible for compatible, _ in parsed['trees']]
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
        'ubootBytes': parsed['ubootBytes'],
        'options': parsed['options'],
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
    except (OSError, ValueError) as error:
        sys.exit(f'Stage 2 check failed: {error}')
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
