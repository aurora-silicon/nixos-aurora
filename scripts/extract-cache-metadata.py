#!/usr/bin/env python3
"""Safely extract a cache snapshot's cache-metadata.tar.gz (narinfo files only)."""
import re
import sys
import tarfile


def extract(archive, destination):
    with tarfile.open(archive) as bundle:
        entries = bundle.getmembers()
        if len(entries) >= 30000 or sum(item.size for item in entries) >= 64 * 1024**2:
            raise ValueError('cache metadata exceeds its budget')
        for item in entries:
            if not item.isfile() or not (item.name == 'index.html'
                                         or re.fullmatch(r'cache/(nix-cache-info|[a-z0-9]{32}[.]narinfo)', item.name)):
                raise ValueError(f'unexpected cache metadata entry: {item.name}')
        bundle.extractall(destination, filter='data')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('usage: extract-cache-metadata.py ARCHIVE DESTINATION')
    extract(sys.argv[1], sys.argv[2])
