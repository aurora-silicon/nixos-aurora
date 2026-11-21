#!/usr/bin/env python3
"""Mirror an authenticated Nix cache to an S3-compatible bucket (Cloudflare R2).

GitHub Pages answers bursts of narinfo lookups with HTTP 429, and anonymous
release-asset downloads are throttled, so the cache is also served as plain
static files from a bucket: `nix-cache-info`, `<hash>.narinfo` and
`nar/<FileHash>.nar.<ext>`, the layout `nix copy --to file://` writes.

  plan    rewrite each narinfo's URL to the bucket's relative `nar/<file>` and
          list the NARs to copy. A Nix signature covers the store path, NAR
          hash, NAR size and references, not URL, so the signatures stay valid.
  upload  copy every missing NAR (checked against FileHash and FileSize), then
          the narinfo files, then nix-cache-info, so a client never sees an
          entry whose NAR is not there yet.

`upload` uses the AWS CLI with R2's S3 endpoint. It reads AWS_ACCESS_KEY_ID,
AWS_SECRET_ACCESS_KEY, R2_ACCOUNT_ID, R2_BUCKET and R2_PREFIX from the
environment and GH_TOKEN for authenticated release downloads (not API calls).
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

NIX32 = '0123456789abcdfghijklmnpqrsvwxyz'
NARINFO = re.compile(r'[a-z0-9]{32}\.narinfo')
RELEASE = re.compile(r'https://github\.com/(?P<repository>aurora-silicon/nixos-aurora)/releases/download/'
                     r'(?P<tag>cache-[A-Za-z0-9._-]+)/(?P<name>[^/]+)')
EXTENSIONS = {'zstd': '.zst', 'xz': '.xz', 'bzip2': '.bz2', 'gzip': '.gz', 'none': ''}
# Long-lived, never re-encoded on the wire: a NAR's name is its own hash.
IMMUTABLE = 'public, max-age=31536000, immutable, no-transform'
NARINFO_CACHE = 'public, max-age=3600, no-transform'
CACHE_INFO = 'public, max-age=300, no-transform'


def nix32_decode(text):
    """Nix's base-32 (libutil hash.cc): the last character holds the lowest bits."""
    size = len(text) * 5 // 8
    out = bytearray(size)
    for n in range(len(text)):
        digit = NIX32.index(text[len(text) - n - 1])
        i, j = divmod(n * 5, 8)
        out[i] |= (digit << j) & 0xff
        if i < size - 1:
            out[i + 1] |= digit >> (8 - j)
        elif digit >> (8 - j):
            raise ValueError(f'invalid base-32 hash: {text}')
    return bytes(out)


def parse(text):
    fields = {}
    for line in text.splitlines():
        name, separator, value = line.partition(': ')
        if not separator:
            raise ValueError(f'malformed narinfo line: {line!r}')
        if name != 'Sig':
            if name in fields:
                raise ValueError(f'duplicate narinfo field {name}')
            fields[name] = value
    return fields


def nar_entry(info, fields):
    """The bucket key and source of one narinfo's NAR."""
    algorithm, _, digest = fields['FileHash'].partition(':')
    if algorithm != 'sha256' or not re.fullmatch(f'[{NIX32}]{{52}}', digest):
        raise ValueError(f'{info.name}: FileHash must be a base-32 sha256')
    compression = fields.get('Compression', 'bzip2')
    if compression not in EXTENSIONS:
        raise ValueError(f'{info.name}: unknown compression {compression}')
    name = f'{digest}.nar{EXTENSIONS[compression]}'
    url = fields['URL']
    match = RELEASE.fullmatch(url)
    if match:
        if match['name'] != name:
            raise ValueError(f'{info.name}: {url} is not named after its FileHash')
        source = {'repository': match['repository'], 'tag': match['tag']}
    elif url == f'nar/{name}':
        source = None
    else:
        raise ValueError(f'{info.name}: URL {url} is neither an Aurora cache release nor nar/<FileHash>')
    size = int(fields['FileSize'])
    if size <= 0:
        raise ValueError(f'{info.name}: FileSize must be positive')
    return {'key': f'nar/{name}', 'name': name, 'size': size, 'sha256': nix32_decode(digest).hex(),
            'source': source}


def plan(cache, output):
    """Write the bucket's metadata to `output` and return the upload plan."""
    if (output / 'cache').exists():
        raise SystemExit(f'{output}/cache exists; use a new output directory')
    (output / 'cache').mkdir(parents=True)
    if not (cache / 'nix-cache-info').is_file():
        raise ValueError('the cache has no nix-cache-info')
    nars, metadata = {}, []
    for info in sorted(cache.glob('*.narinfo')):
        if info.is_symlink() or not NARINFO.fullmatch(info.name):
            raise ValueError(f'unsafe narinfo name {info.name}')
        text = info.read_text()
        fields = parse(text)
        entry = nar_entry(info, fields)
        if entry['source'] is None:
            raise ValueError(f'{info.name}: its NAR is not in a release; nothing to copy it from')
        previous = nars.setdefault(entry['key'], entry)
        if (previous['size'], previous['sha256']) != (entry['size'], entry['sha256']):
            raise ValueError(f'{entry["key"]} is listed with two sizes')
        lines = text.splitlines(keepends=True)
        rewritten = ''.join(f'URL: {entry["key"]}\n' if line.startswith('URL: ') else line for line in lines)
        if parse(rewritten) != dict(fields, URL=entry['key']) or rewritten.count('URL: ') != 1:
            raise AssertionError(f'{info.name}: only the URL line may change')
        (output / 'cache' / info.name).write_text(rewritten)
        metadata.append({'key': info.name, 'content_type': 'text/x-nix-narinfo', 'cache_control': NARINFO_CACHE})
    if not metadata:
        raise ValueError('the cache has no narinfo files')
    shutil.copyfile(cache / 'nix-cache-info', output / 'cache' / 'nix-cache-info')
    metadata.append({'key': 'nix-cache-info', 'content_type': 'text/x-nix-cache-info', 'cache_control': CACHE_INFO})
    result = {'schema': 1, 'nars': sorted(nars.values(), key=lambda item: item['key']), 'metadata': metadata,
              'nar_bytes': sum(item['size'] for item in nars.values())}
    (output / 'plan.json').write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    return result


class Bucket:
    """The few S3 calls the mirror needs, through the AWS CLI."""

    def __init__(self, account, bucket, prefix):
        if not re.fullmatch(r'[0-9a-f]{32}', account):
            raise SystemExit('R2_ACCOUNT_ID must be the 32-character account id')
        self.bucket, self.prefix = bucket, prefix.strip('/')
        self.base = ['aws', 's3api', '--endpoint-url', f'https://{account}.r2.cloudflarestorage.com',
                     '--region', 'auto', '--output', 'json']
        # R2 rejects the CRC checksums newer AWS CLI releases send by default.
        self.env = dict(os.environ, AWS_REQUEST_CHECKSUM_CALCULATION='when_required',
                        AWS_RESPONSE_CHECKSUM_VALIDATION='when_required')

    def key(self, name):
        return f'{self.prefix}/{name}' if self.prefix else name

    def existing(self, folder):
        listed = subprocess.run(self.base + ['list-objects-v2', '--bucket', self.bucket,
                                             '--prefix', self.key(folder) + '/'],
                                check=True, capture_output=True, text=True, env=self.env).stdout
        objects = json.loads(listed or '{}').get('Contents', [])
        return {item['Key']: int(item['Size']) for item in objects}

    def put(self, name, path, content_type, cache_control, sha256):
        subprocess.run(self.base + ['put-object', '--bucket', self.bucket, '--key', self.key(name),
                                    '--body', str(path), '--content-type', content_type,
                                    '--cache-control', cache_control, '--metadata', f'sha256={sha256}'],
                       check=True, capture_output=True, text=True, env=self.env)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def copy_nar(bucket, entry, work):
    source = entry['source']
    url = f'https://github.com/{source["repository"]}/releases/download/{source["tag"]}/{entry["name"]}'
    with tempfile.TemporaryDirectory(dir=work) as directory:
        path = Path(directory) / entry['name']
        # The release download URL, not the REST API: thousands of NARs would
        # exhaust GITHUB_TOKEN's 1,000 API requests an hour. The token makes the
        # download authenticated; curl drops it on the redirect to the asset host.
        subprocess.run(['curl', '-fsSL', '--retry', '6', '--retry-all-errors', '--retry-delay', '5',
                        '-H', 'Authorization: Bearer ' + os.environ['GH_TOKEN'], '-o', str(path), url], check=True)
        if path.stat().st_size != entry['size'] or sha256_file(path) != entry['sha256']:
            raise ValueError(f'{entry["name"]} does not match its FileHash and FileSize')
        bucket.put(entry['key'], path, 'application/x-nix-nar', IMMUTABLE, entry['sha256'])
    return entry['size']


def upload(plan_path, cache, work, jobs):
    data = json.loads(plan_path.read_text())
    if data.get('schema') != 1:
        raise SystemExit('unknown plan schema')
    env = os.environ
    missing = [name for name in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'R2_ACCOUNT_ID', 'R2_BUCKET', 'GH_TOKEN')
               if not env.get(name)]
    if missing:
        raise SystemExit('upload needs ' + ', '.join(missing))
    bucket = Bucket(env['R2_ACCOUNT_ID'], env['R2_BUCKET'], env.get('R2_PREFIX', 'nixos-aurora/cache'))
    present = bucket.existing('nar')
    todo = [entry for entry in data['nars'] if present.get(bucket.key(entry['key'])) != entry['size']]
    print(f'{len(data["nars"]) - len(todo)} NARs already in the bucket; copying {len(todo)} '
          f'({sum(entry["size"] for entry in todo) / 1e9:.2f} GB)')
    work.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        copied = sum(pool.map(lambda entry: copy_nar(bucket, entry, work), todo))
    # Metadata last, nix-cache-info (last in the plan) at the very end.
    for item in data['metadata']:
        path = cache / item['key']
        bucket.put(item['key'], path, item['content_type'], item['cache_control'], sha256_file(path))
    print(f'Copied {copied / 1e9:.2f} GB of NARs and {len(data["metadata"])} metadata files to '
          f'{env["R2_BUCKET"]}/{bucket.prefix}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    planning = commands.add_parser('plan')
    planning.add_argument('--cache', type=Path, required=True, help='authenticated cache directory')
    planning.add_argument('--output', type=Path, required=True)
    uploading = commands.add_parser('upload')
    uploading.add_argument('--plan', type=Path, required=True)
    uploading.add_argument('--cache', type=Path, required=True, help='the planned (rewritten) cache directory')
    uploading.add_argument('--work', type=Path, required=True)
    uploading.add_argument('--jobs', type=int, default=6)
    args = parser.parse_args()
    if args.command == 'plan':
        result = plan(args.cache, args.output)
        print(f'{len(result["metadata"]) - 1} narinfo files, {len(result["nars"])} NARs '
              f'({result["nar_bytes"] / 1e9:.2f} GB)')
    else:
        upload(args.plan, args.cache, args.work, args.jobs)


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    main()
