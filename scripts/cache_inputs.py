#!/usr/bin/env python3
"""Shared validation and transport for native CI cache artifacts.

Image imports and signed publication keep their own acceptance policies.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

import os

# gh with retries of transient GitHub API failures (HTTP 5xx/429, timeouts): scripts/gh-retry
GH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gh-retry')

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'aurora-silicon/nixos-aurora'
STORE_PATH = re.compile(r'/nix/store/[a-z0-9]{32}-[^/\s]+')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def gh_json(route):
    return json.loads(subprocess.check_output([GH, 'api', route]))


def validate_build(metadata, ancestor):
    commit = metadata.get('head_sha', '')
    if (metadata.get('conclusion') != 'success'
            or metadata.get('head_repository', {}).get('full_name') != REPOSITORY
            or metadata.get('event') not in ('push', 'workflow_dispatch')
            or (metadata.get('event') == 'push' and metadata.get('head_branch') != 'main')
            or metadata.get('path') != '.github/workflows/checks.yml'
            or not re.fullmatch('[a-f0-9]{40}', commit) or not ancestor(commit)):
        raise ValueError('Not a successful merged native main-branch or manual build')


def expected_outputs(commit=None):
    commit = commit or subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('Expected a full source commit')
    reference = 'git+' + ROOT.as_uri() + '?rev=' + commit
    expression = ('packages: builtins.mapAttrs (_: value: { drvPath = value.drvPath; '
                  'outputs = map (name: value.${name}.outPath) value.outputs; }) packages')
    return json.loads(subprocess.check_output([
        'nix', 'eval', '--json', reference + '#packages.aarch64-linux', '--apply', expression,
    ], text=True))


def require_coverage(expected, covered):
    missing = sorted(name for name, item in expected.items() if not set(item['outputs']) <= covered)
    if missing:
        raise ValueError('Cache omits current hardware outputs: ' + ', '.join(missing))


def graphics_evidence(path):
    """checks.yml keeps the graphics package's generation switch evidence
    (graphics-generation/*.txt and *.sha256) beside its build record. It is
    extracted with the artifact but never read or published from here."""
    return (path.parts[:1] == ('graphics-generation',)
            and (len(path.parts) == 1 or len(path.parts) == 2 and path.suffix in ('.txt', '.sha256')))


def unpack(archive, directory):
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        if len(entries) > 30_000 or sum(item.file_size for item in entries) > 4 * 1024**3:
            raise ValueError('Expanded cache artifact exceeds its budget')
        names = set()
        for item in entries:
            path = Path(item.filename)
            mode = (item.external_attr >> 16) & 0o170000
            if (path.is_absolute() or '..' in path.parts or '\\' in item.filename
                    or item.filename in names or mode not in (0, 0o040000, 0o100000)):
                raise ValueError('Unsafe cache artifact entry')
            names.add(item.filename)
            if not (path.parts and path.parts[0] == 'cache'
                    or item.filename in ('build.json', 'closure.json')
                    or graphics_evidence(path)):
                raise ValueError('Unexpected cache artifact path')
        # Budget the extracted input plus a verified merged copy before writing.
        peak = 2 * sum(item.file_size for item in entries)
        if shutil.disk_usage(directory.parent).free < 10 * 1024**3 + peak:
            raise ValueError('Insufficient space for extraction and the merged cache')
        package.extractall(directory)


def current_build(record, expected):
    return (isinstance(record, list) and len(record) == 1
            and record[0].get('drvPath') == expected['drvPath']
            and isinstance(record[0].get('outputs'), dict)
            and set(record[0]['outputs'].values()) == set(expected['outputs']))


def merge_file(source, target):
    if source.is_symlink() or not source.is_file():
        raise ValueError('Cache input must be a regular file')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if digest(source) != digest(target):
            # Independently verified exports may carry different signature sets.
            # Keep the first valid signature only when every other field agrees.
            if source.suffix != '.narinfo':
                raise ValueError('Conflicting cache transport: ' + source.name)
            without_signatures = lambda p: [line for line in p.read_text().splitlines()
                                             if not line.startswith('Sig: ')]
            if without_signatures(source) != without_signatures(target):
                raise ValueError('Conflicting cache identity: ' + source.name)
    else:
        shutil.copyfile(source, target)
        if digest(source) != digest(target):
            raise ValueError('Cache copy verification failed')


def store_paths(directory):
    result = set()
    for path in directory.glob('*.narinfo'):
        if (path.is_symlink() or path.stat().st_size > 1024**2
                or not re.fullmatch('[a-z0-9]{32}[.]narinfo', path.name)):
            raise ValueError('Unsafe NAR metadata filename')
        lines = [line.removeprefix('StorePath: ') for line in path.read_text().splitlines()
                 if line.startswith('StorePath: ')]
        if len(lines) != 1 or not STORE_PATH.fullmatch(lines[0]):
            raise ValueError('Invalid signed store path')
        if path.stem != Path(lines[0]).name.split('-', 1)[0]:
            raise ValueError('Store path does not match metadata filename')
        result.add(lines[0])
    return result


class MissingOutputs(ValueError):
    def __init__(self, packages):
        super().__init__('Current output proofs missing for: ' + ', '.join(packages))
        self.packages = packages


def newest_per_name(artifacts):
    """A re-run job uploads under the same name; only the newest upload
    belongs to the attempt that made the run succeed."""
    newest = {}
    for artifact in artifacts:
        current = newest.get(artifact['name'])
        if current is None or (artifact.get('created_at', ''), artifact['id']) > (current.get('created_at', ''), current['id']):
            newest[artifact['name']] = artifact
    return sorted(newest.values(), key=lambda artifact: artifact['name'])


def attests(commit):
    workflow = subprocess.run(['git', 'show', f'{commit}:.github/workflows/checks.yml'], cwd=ROOT,
                              capture_output=True, text=True)
    return 'actions/attest-build-provenance' in workflow.stdout


def verify_attestation(archive, commit):
    subprocess.run([GH, 'attestation', 'verify', str(archive), '--repo', REPOSITORY,
                    '--signer-workflow', f'{REPOSITORY}/.github/workflows/checks.yml',
                    '--source-digest', commit, '--deny-self-hosted-runners'],
                   check=True, stdout=subprocess.DEVNULL)


@contextmanager
def authenticated_artifact(artifact, commit, *, require_attestation=True, parent=None):
    """Yield bounded extracted bytes after digest and provenance verification."""
    if artifact['expired'] or artifact['size_in_bytes'] > 2 * 1024**3:
        raise ValueError('Required artifact is unavailable or exceeds its budget')
    with tempfile.TemporaryDirectory(prefix='aurora-cache-input-', dir=parent) as temporary:
        staging = Path(temporary)
        if shutil.disk_usage(staging).free < 10 * 1024**3 + 6 * 1024**3:
            raise ValueError('Insufficient space for a bounded cache import')
        archive = staging / 'artifact.zip'
        with archive.open('xb') as stream:
            subprocess.run([GH, 'api', f'repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip'],
                           stdout=stream, check=True)
        if 'sha256:' + digest(archive) != artifact['digest']:
            raise ValueError('Native artifact digest mismatch')
        if require_attestation:
            verify_attestation(archive, commit)
        unpack(archive, staging / 'unpacked')
        yield staging / 'unpacked'


def verified_cache(source, expected):
    """Return a matching build and complete verified cache, or skip a stale one."""
    if not (source / 'build.json').is_file() or not (source / 'cache').is_dir():
        return None
    build = json.loads((source / 'build.json').read_text())
    if not current_build(build, expected):
        return None
    cache = source / 'cache'
    subprocess.run(['nix', 'store', 'verify', '--store', cache.as_uri(), '--all', '--no-trust'], check=True)
    paths = store_paths(cache)
    if not set(expected['outputs']) <= paths:
        raise ValueError('The verified cache omits a declared output')
    return build, cache, paths


NAR_HASH = re.compile(r'sha256-[A-Za-z0-9+/]{43}=')


def nar_hashes(data):
    if isinstance(data, list):
        data = {item['path']: item for item in data}
    if not isinstance(data, dict) or not data or len(data) > 30_000:
        raise ValueError('Expected a bounded nonempty Nix closure')
    result = {}
    for path, info in data.items():
        value = info.get('narHash', '') if isinstance(info, dict) else ''
        if not STORE_PATH.fullmatch(path) or not NAR_HASH.fullmatch(value):
            raise ValueError('Invalid Nix closure path or NAR hash')
        result[path] = value
    return result
