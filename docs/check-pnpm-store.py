#!/usr/bin/env python3
"""Reject pnpm 11 fetches that silently omit optional locked packages."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys


def check(expected_file, index_dump):
    expected = set(json.loads(Path(expected_file).read_text()))
    # Inspect the fetcher's normalized SQL dump entirely in memory. Opening
    # pnpm's live WAL database could affect sidecars or miss pending records.
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.executescript(Path(index_dump).read_text())
        keys = [key for (key,) in connection.execute("SELECT key FROM package_index")]
    # The pinned pnpm stores one package per integrity<TAB>name@version key.
    actual = {key.partition("\t")[2] for key in keys}
    missing = sorted(expected - actual)
    if missing:
        raise ValueError(
            f"pnpm omitted {len(missing)} locked package(s), possibly after optional download failures. "
            "Retry the fetch; do not replace the complete-store hash.\n" + "\n".join(missing)
        )


if __name__ == "__main__":
    try:
        check(*sys.argv[1:])
    except (OSError, ValueError, sqlite3.Error) as error:
        sys.exit(str(error))
