#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Rebuild the source-only libane archive from individually hash-pinned text files."""
import argparse
import concurrent.futures
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    pin = json.loads((ROOT / 'sources.json').read_text())['libane']

    def fetch(record):
        with urllib.request.urlopen(record['url'], timeout=60) as stream:
            data = stream.read()
        if hashlib.sha256(data).hexdigest() != record['sha256']:
            raise ValueError(record['path'] + ': SHA-256 mismatch')
        return record['path'], data

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        files = list(pool.map(fetch, pin['source_files']))
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for path, data in sorted(files):
            # A fixed allowlist, hashes and canonical tar metadata keep unrelated
            # fixtures, compiled programs and firmware out of source packages.
            if path != 'LICENSE' and path != 'ane/src/uapi/drm/ane_accel.h' and not (
                    path.startswith('libane/') and path.count('/') == 1 and
                    (path.endswith(('.c', '.h')) or path == 'libane/Makefile')):
                raise ValueError('unexpected library source path: ' + path)
            entry = tarfile.TarInfo(pin['archive_root'] + '/' + path)
            entry.size = len(data)
            entry.mode = 0o644
            archive.addfile(entry, io.BytesIO(data))
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0) as stream:
        stream.write(raw.getvalue())
    content = output.getvalue()
    if hashlib.sha256(content).hexdigest() != pin['sha256']:
        raise ValueError('rebuilt source archive SHA-256 mismatch')
    destination = args.output or ROOT / pin['local_archive']
    destination.write_bytes(content)
    print(pin['sha256'], destination)


if __name__ == '__main__':
    main()
