#!/usr/bin/env python3
"""Add the Stage 2 files a Stage 1 with the CTXR window chainloads.

An installer payload's ESP gets boot-ctxr.bin, a copy of the combined boot.bin,
and boot-ctxr-<board>.bin, a copy of boot-<board>.bin for each board that boots
a Mach-O Stage 1. prepare-stage2.py refuses boot-*.bin in its output directory,
so this runs after it. A second run replaces what the first one wrote.

Any problem fails an image build. With --keep-going, for a rebuild that runs on
every Mac, a problem with one file only leaves that file out.

usage: prepare-ctxr-stage2.py [--keep-going] SOURCE [OUTPUT]
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import struct
import sys

DTB_MAGIC = b'\xd0\x0d\xfe\xed'
BOARD_FILE = re.compile(r'boot-(j[0-9]+[a-z]*)\.bin')
# The boards assemble-distribution-payload.py requires in every payload.
REQUIRED_BOARDS = ('j700', 'j616s', 'j614s')
# Aura's Stage 2 slot on these Macs.
MAX_STAGE2_BYTES = 16 * 1024 * 1024


def uses_macho(compatible):
    """The installer's AuraStage1Format.usesMachO, read from a root compatible."""
    for entry in compatible:
        found = re.fullmatch(r'apple,t([0-9a-f]{4})', entry)
        if found:
            chip = int(found[1], 16)
            if 0x8130 <= chip <= 0x8FFF or 0x6040 <= chip <= 0x6FFF:
                return True
    return False


def root_compatible(blob):
    """The root node's compatible strings of the device tree at the start of blob."""
    if len(blob) < 40:
        raise ValueError('short device tree')
    fields = struct.unpack_from('>10I', blob)
    magic, total, struct_offset, strings_offset = fields[:4]
    strings_size, struct_size = fields[8], fields[9]
    if (magic != 0xD00DFEED or total > len(blob)
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
            return [item.decode('ascii', 'replace') for item in value.split(b'\0') if item]
    raise ValueError('device tree root has no compatible')


def board_compatible(image, board):
    """The compatible strings of the device tree for board in a board Stage 2."""
    cursor = image.find(DTB_MAGIC)
    while cursor >= 0:
        try:
            compatible = root_compatible(image[cursor:])
        except (ValueError, struct.error):
            compatible = []
        if compatible and compatible[0] == 'apple,' + board:
            return compatible
        cursor = image.find(DTB_MAGIC, cursor + 1)
    raise ValueError(f'boot-{board}.bin has no device tree for {board}')


def copy(source, target):
    size = source.stat().st_size
    if size > MAX_STAGE2_BYTES:
        raise ValueError(f'{source.name} is {size} bytes, over the {MAX_STAGE2_BYTES} byte slot')
    shutil.copyfile(source, target)
    if target.read_bytes() != source.read_bytes():
        raise ValueError(f'{target.name} does not match {source.name}')


def prepare(source, output, keep_going=False):
    def attempt(step):
        try:
            step()
        except ValueError as error:
            if not keep_going:
                raise
            print(f'warning: {error}; leaving it out', file=sys.stderr)
            return False
        return True

    output.mkdir(parents=True, exist_ok=True)
    written = []
    if (source / 'boot.bin').is_file():
        if attempt(lambda: copy(source / 'boot.bin', output / 'boot-ctxr.bin')):
            written.append('boot-ctxr.bin')
    boards = set()

    def add_board(path, board):
        if uses_macho(board_compatible(path.read_bytes(), board)):
            copy(path, output / f'boot-ctxr-{board}.bin')
            written.append(f'boot-ctxr-{board}.bin')
            boards.add(board)

    for path in sorted(source.iterdir()):
        found = BOARD_FILE.fullmatch(path.name)
        if found:
            attempt(lambda: add_board(path, found[1]))
    missing = [board for board in REQUIRED_BOARDS if board not in boards]
    if missing and not keep_going:
        raise ValueError('no board Stage 2 for ' + ', '.join(missing))
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--keep-going', action='store_true')
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path, nargs='?')
    args = parser.parse_args()
    try:
        written = prepare(args.source, args.output or args.source, args.keep_going)
    except (OSError, ValueError) as error:
        sys.exit(f'CTXR Stage 2 preparation failed: {error}')
    print(json.dumps(written))


if __name__ == '__main__':
    main()
