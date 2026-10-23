#!/usr/bin/env python3
"""Collect current Nix outputs from authenticated native CI cache artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'aurora-silicon/nixos-aurora'
STORE_PATH = re.compile(r'/nix/store/[a-z0-9]{32}-[^/\s]+')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def gh_json(route):
    return json.loads(subprocess.check_output(['gh', 'api', route]))


def validate_build(metadata, ancestor):
    commit = metadata.get('head_sha', '')
    if (metadata.get('conclusion') != 'success'
            or metadata.get('head_repository', {}).get('full_name') != REPOSITORY
            or metadata.get('event') not in ('push', 'workflow_dispatch')
            or (metadata.get('event') == 'push' and metadata.get('head_branch') != 'main')
            or metadata.get('path') != '.github/workflows/checks.yml'
            or not re.fullmatch('[a-f0-9]{40}', commit) or not ancestor(commit)):
        raise ValueError('Not a successful merged native main-branch or manual build')


def expected_outputs():
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    reference = 'git+' + ROOT.as_uri() + '?rev=' + commit
    expression = ('packages: builtins.mapAttrs (_: value: { drvPath = value.drvPath; '
                  'outputs = map (name: value.${name}.outPath) value.outputs; }) packages')
    return json.loads(subprocess.check_output([
        'nix', 'eval', '--json', reference + '#packages.aarch64-linux', '--apply', expression,
    ], text=True))


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
                    or item.filename in ('build.json', 'closure.json')):
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
    subprocess.run(['gh', 'attestation', 'verify', str(archive), '--repo', REPOSITORY,
                    '--signer-workflow', f'{REPOSITORY}/.github/workflows/checks.yml',
                    '--source-digest', commit, '--deny-self-hosted-runners'],
                   check=True, stdout=subprocess.DEVNULL)


def collect(runs, output, previous):
    if output.exists():
        raise ValueError('Use a new candidate cache directory')
    expected = expected_outputs()
    covered = store_paths(previous) if previous else set()
    needed = {name for name, item in expected.items() if not set(item['outputs']) <= covered}
    output.mkdir(parents=True)
    records = []
    for run in runs:
        metadata = gh_json(f'repos/{REPOSITORY}/actions/runs/{run}')
        validate_build(metadata, lambda commit: subprocess.run(
            ['git', 'merge-base', '--is-ancestor', commit, 'HEAD'], cwd=ROOT).returncode == 0)
        listing = gh_json(f'repos/{REPOSITORY}/actions/runs/{run}/artifacts?per_page=100')
        if listing['total_count'] > 100:
            raise ValueError('Unexpected native artifact matrix size')
        for artifact in newest_per_name(listing['artifacts']):
            match = re.fullmatch(r'nix-([a-z0-9-]+)-closure', artifact['name'])
            if match is None or match[1] not in needed:
                continue
            if artifact['expired'] or artifact['size_in_bytes'] > 2 * 1024**3:
                raise ValueError('Required artifact is unavailable or exceeds its budget')
            with tempfile.TemporaryDirectory(prefix='aurora-cache-input-', dir=output.parent) as temporary:
                staging = Path(temporary)
                if shutil.disk_usage(staging).free < 10 * 1024**3 + 6 * 1024**3:
                    raise ValueError('Insufficient space for a bounded cache import')
                archive = staging / 'artifact.zip'
                with archive.open('xb') as stream:
                    subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip'],
                                   stdout=stream, check=True)
                if 'sha256:' + digest(archive) != artifact['digest']:
                    raise ValueError('Native artifact digest mismatch')
                if attests(metadata['head_sha']):
                    verify_attestation(archive, metadata['head_sha'])
                unpack(archive, staging / 'unpacked')
                source = staging / 'unpacked'
                if not (source / 'build.json').is_file() or not (source / 'cache').is_dir():
                    # Not an output of a successful build (an older layout's
                    # failed attempt); a newer upload carries the real one.
                    print(f'Skipping artifact {artifact["id"]}: no build record', file=sys.stderr)
                    continue
                build = json.loads((source / 'build.json').read_text())
                if not current_build(build, expected[match[1]]):
                    continue
                cache = source / 'cache'
                # Builds export unsigned caches; check every NAR against its
                # metadata here. publish-cache.yml signs after this check.
                subprocess.run(['nix', 'store', 'verify', '--store', cache.as_uri(), '--all', '--no-trust'],
                               check=True)
                paths = store_paths(cache)
                if not set(expected[match[1]]['outputs']) <= paths:
                    raise ValueError('The signed cache omits a declared output')
                for path in cache.rglob('*'):
                    if path.is_dir():
                        continue
                    relative = path.relative_to(cache)
                    if not (relative.name == 'nix-cache-info' and len(relative.parts) == 1
                            or re.fullmatch(r'[a-z0-9]{32}[.]narinfo', str(relative))
                            or re.fullmatch(r'nar/[a-z0-9]+[.]nar[.](zst|xz)', str(relative))):
                        # closure.json is evidence, not a cache object.
                        if str(relative) == 'closure.json':
                            continue
                        raise ValueError('Unexpected exported cache file')
                    merge_file(path, output / relative)
                covered.update(paths)
                records.append({'run': run, 'commit': metadata['head_sha'], 'artifact_id': artifact['id'],
                                'artifact_digest': artifact['digest'], 'package': match[1], 'build': build})
                needed = {name for name in needed if not set(expected[name]['outputs']) <= covered}
    if needed:
        raise MissingOutputs(sorted(needed))
    if not records:
        raise ValueError('The previous snapshot already covers every current output')
    return {'schema': 1, 'expected': expected, 'native_inputs': records,
            'previous_metadata': previous is not None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--previous-metadata', type=Path)
    parser.add_argument('--missing-output', type=Path,
                        help='when outputs lack a current build, write the flake packages to rebuild and exit 3')
    args = parser.parse_args()
    if any(not re.fullmatch('[0-9]+', run) for run in args.runs):
        parser.error('Expected numeric native build IDs')
    try:
        proof = collect(args.runs, args.output.resolve(), args.previous_metadata)
    except MissingOutputs as error:
        if args.missing_output:
            args.missing_output.write_text(' '.join(error.packages) + '\n')
            print(error, file=sys.stderr)
            raise SystemExit(3)
        raise
    args.output.with_suffix('.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(f'Authenticated {len(proof["native_inputs"])} native cache inputs')


if __name__ == '__main__':
    main()
