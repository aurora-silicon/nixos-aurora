#!/usr/bin/env python3
"""Print the next unused <prefix>YYYYMMDD.N tag for today (UTC); tags on stdin."""
import datetime
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import updatelib as lib  # noqa: E402

if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: next-tag.py PREFIX < existing-tags')
    today = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d')
    print(lib.next_snapshot_tag(sys.stdin.read().split(), sys.argv[1], today))
