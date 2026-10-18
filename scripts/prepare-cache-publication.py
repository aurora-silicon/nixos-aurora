#!/usr/bin/env python3
"""Prepare signed Nix cache metadata and immutable release assets."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile

BASE = r'https://github\.com/aurora-silicon/nixos-aurora/releases/download/cache-[A-Za-z0-9._-]+'
SIGNED_FIELDS = ('StorePath', 'NarHash', 'NarSize', 'References')
TRANSPORT_FIELDS = ('Compression', 'FileHash', 'FileSize')


def fields(text):
    result = {}
    for line in text.splitlines():
        name, value = line.split(': ', 1)
        if name != 'Sig' and name in result:
            raise ValueError('duplicate cache metadata field: ' + name)
        if name != 'Sig':
            result[name] = value
    for name in (*SIGNED_FIELDS, *TRANSPORT_FIELDS, 'URL'):
        if name not in result:
            raise ValueError('missing cache metadata field: ' + name)
    return result


def identity(values):
    return tuple(values[name] for name in SIGNED_FIELDS)


def prepare(source, destination, asset_base, previous_metadata=None):
    if destination.exists():
        raise ValueError('output exists; use a new snapshot directory')
    if not re.fullmatch(BASE, asset_base):
        raise ValueError('expected an immutable Aurora NixOS release asset base')
    previous_entries = {}
    if previous_metadata is not None:
        for previous in sorted(previous_metadata.glob('*.narinfo')):
            if previous.is_symlink() or not re.fullmatch(r'[a-z0-9]{32}\.narinfo', previous.name):
                raise ValueError('unsafe previous cache metadata')
            previous_entries[previous.name] = (previous, fields(previous.read_text()))
    site, assets = destination / 'site/cache', destination / 'assets'
    site.mkdir(parents=True)
    assets.mkdir()
    records = []
    for info in sorted(source.glob('*.narinfo')):
        if info.is_symlink() or not re.fullmatch(r'[a-z0-9]{32}\.narinfo', info.name):
            raise ValueError('unsafe cache metadata path')
        text = info.read_text()
        values = fields(text)
        nar = values['URL']
        if not re.fullmatch(r'nar/[a-z0-9]+\.nar\.(zst|xz)', nar):
            raise ValueError('unexpected local NAR path')
        path = source / nar
        if not path.is_file() or path.is_symlink():
            raise ValueError('missing NAR archive')
        target = assets / path.name
        transport = asset_base + '/' + path.name
        reused = None
        if info.name in previous_entries:
            previous = previous_entries[info.name][1]
            if identity(previous) != identity(values):
                raise ValueError('conflicting signed store identity: ' + info.name)
            # Reuse a byte-identical immutable transport, retaining the current
            # NAR signature. The deploy gate still verifies every HTTP NAR.
            if (re.fullmatch(BASE + '/' + re.escape(path.name), previous['URL'])
                    and all(previous[name] == values[name] for name in TRANSPORT_FIELDS)):
                reused = transport = previous['URL']
        if reused is None:
            if target.exists() and target.read_bytes() != path.read_bytes():
                raise ValueError('conflicting NAR asset identity')
            shutil.copyfile(path, target)
        # A Nix cache signature covers path, NAR digest/size and references.
        # Transport location is independent; clients verify the signed NAR.
        text = text.replace('URL: ' + nar + '\n', 'URL: ' + transport + '\n')
        (site / info.name).write_text(text)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        record = {'store_path': values['StorePath'], 'asset': path.name,
                  'bytes': path.stat().st_size, 'sha256': digest}
        if reused is not None:
            record['reused_from'] = reused
        records.append(record)
    if not records:
        raise ValueError('no signed cache entries')
    shutil.copyfile(source / 'nix-cache-info', site / 'nix-cache-info')
    (destination / 'site/index.html').write_text('Aurora NixOS development binary cache\n')
    (assets / 'manifest.json').write_text(json.dumps({'schema': 1, 'asset_base': asset_base, 'paths': records}, indent=2) + '\n')
    if previous_metadata is not None:
        for previous, previous_fields in previous_entries.values():
            target = site / previous.name
            if target.exists():
                if identity(previous_fields) != identity(fields(target.read_text())):
                    raise ValueError('conflicting signed store identity: ' + previous.name)
            else:
                # Keep each older immutable transport URL. Deployment verifies
                # all signatures and NAR contents again before publishing.
                shutil.copyfile(previous, target)
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
    parser.add_argument('--previous-metadata', type=Path)
    args = parser.parse_args()
    print(f'Prepared {len(prepare(args.cache, args.output, args.asset_base, args.previous_metadata))} Nix cache paths')
