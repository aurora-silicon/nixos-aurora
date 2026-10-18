#!/usr/bin/env python3
"""Prepare signed Nix cache metadata and immutable release assets."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile
import urllib.parse


def prepare(source, destination, asset_base):
    if destination.exists():
        raise ValueError('output exists; use a new snapshot directory')
    url = urllib.parse.urlsplit(asset_base)
    if url.scheme != 'https' or url.hostname != 'github.com' or not re.fullmatch(r'/aurora-silicon/nixos-aurora/releases/download/cache-[A-Za-z0-9._-]+', url.path) or url.query or url.fragment:
        raise ValueError('expected an immutable Aurora NixOS release asset base')
    site, assets = destination / 'site/cache', destination / 'assets'
    site.mkdir(parents=True)
    assets.mkdir()
    records = []
    for info in sorted(source.glob('*.narinfo')):
        if info.is_symlink() or not re.fullmatch(r'[a-z0-9]{32}\.narinfo', info.name):
            raise ValueError('unsafe cache metadata path')
        text = info.read_text()
        values = {}
        for line in text.splitlines():
            name, value = line.split(': ', 1)
            values.setdefault(name, []).append(value)
        nar = values['URL'][0]
        if not re.fullmatch(r'nar/[a-z0-9]+\.nar\.(zst|xz)', nar):
            raise ValueError('unexpected local NAR path')
        path = source / nar
        if not path.is_file() or path.is_symlink():
            raise ValueError('missing NAR archive')
        target = assets / path.name
        if target.exists() and target.read_bytes() != path.read_bytes():
            raise ValueError('conflicting NAR asset identity')
        shutil.copyfile(path, target)
        # A Nix cache signature covers path, NAR digest/size and references.
        # Transport location is independent; clients verify the signed NAR.
        text = text.replace('URL: ' + nar + '\n', 'URL: ' + asset_base + '/' + path.name + '\n')
        (site / info.name).write_text(text)
        with target.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        records.append({'store_path': values['StorePath'][0], 'asset': target.name,
                        'bytes': target.stat().st_size, 'sha256': digest})
    if not records:
        raise ValueError('no signed cache entries')
    shutil.copyfile(source / 'nix-cache-info', site / 'nix-cache-info')
    (destination / 'site/index.html').write_text('Aurora NixOS development binary cache\n')
    (assets / 'manifest.json').write_text(json.dumps({'schema': 1, 'asset_base': asset_base, 'paths': records}, indent=2) + '\n')
    with tarfile.open(assets / 'cache-metadata.tar.gz', 'w:gz') as archive:
        for path in sorted((destination / 'site').rglob('*')):
            if path.is_file():
                archive.add(path, arcname=str(path.relative_to(destination / 'site')), recursive=False)
    return records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--asset-base', required=True)
    args = parser.parse_args()
    print(f'Prepared {len(prepare(args.cache, args.output, args.asset_base))} Nix cache paths')
