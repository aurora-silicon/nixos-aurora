#!/usr/bin/env python3
"""Collect current Nix outputs from authenticated native CI cache artifacts."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cache_inputs import (  # noqa: E402
    ROOT, REPOSITORY, MissingOutputs, authenticated_artifact, attests,
    expected_outputs, gh_json, merge_file, newest_per_name, store_paths,
    validate_build, verified_cache,
)


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
            if artifact['expired']:
                continue
            with authenticated_artifact(artifact, metadata['head_sha'],
                                        require_attestation=attests(metadata['head_sha']),
                                        parent=output.parent) as source:
                verified = verified_cache(source, expected[match[1]])
                if verified is None:
                    continue
                build, cache, paths = verified
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
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    return {'schema': 1, 'commit': commit, 'expected': expected, 'native_inputs': records,
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
