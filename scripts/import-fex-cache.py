#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Import this exact commit's x86 guest payload for a native ARM image build.

This is an unsigned, build-local import. It neither publishes a binary cache
nor admits a pull-request artifact to the signed cache publication workflow.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cache_inputs', ROOT / 'scripts/collect-cache-inputs.py')
cache_inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache_inputs)
REPOSITORY = cache_inputs.REPOSITORY


def validate_run(metadata, commit):
    if (not re.fullmatch('[0-9a-f]{40}', commit)
            or metadata.get('head_sha') != commit
            or metadata.get('conclusion') != 'success'
            or metadata.get('head_repository', {}).get('full_name') != REPOSITORY
            or metadata.get('path') != '.github/workflows/checks.yml'
            or metadata.get('event') not in ('push', 'pull_request', 'workflow_dispatch')):
        raise ValueError('FEX import requires a successful checks build of this exact repository commit')


def import_build(commit):
    listing = cache_inputs.gh_json(
        f'repos/{REPOSITORY}/actions/workflows/checks.yml/runs?head_sha={commit}&per_page=100')
    runs = sorted(listing['workflow_runs'], key=lambda run: run['id'], reverse=True)
    matching = []
    for run in runs:
        try:
            validate_run(run, commit)
        except ValueError:
            continue
        matching.append(run)
    if not matching:
        raise ValueError('No successful checks build for this commit; finish package CI before building its image')
    run = matching[0]
    listing = cache_inputs.gh_json(f'repos/{REPOSITORY}/actions/runs/{run["id"]}/artifacts?per_page=100')
    if listing['total_count'] > 100:
        raise ValueError('Unexpected artifact matrix size')
    artifacts = [artifact for artifact in cache_inputs.newest_per_name(listing['artifacts'])
                 if artifact['name'] == 'nix-fex-mesa-closure']
    if len(artifacts) != 1 or artifacts[0]['expired'] or artifacts[0]['size_in_bytes'] > 256 * 1024**2:
        raise ValueError('The bounded x86 guest build artifact is missing or unavailable')
    artifact = artifacts[0]
    reference = 'git+' + ROOT.as_uri() + '?rev=' + commit + '#packages.aarch64-linux.fex-mesa'
    expression = 'value: { drvPath = value.drvPath; outputs = map (name: value.${name}.outPath) value.outputs; }'
    expected = json.loads(subprocess.check_output(['nix', 'eval', '--json', reference,
                                                   '--apply', expression], text=True))
    with tempfile.TemporaryDirectory(prefix='aurora-fex-input-') as temporary:
        staging = Path(temporary)
        archive = staging / 'artifact.zip'
        with archive.open('xb') as stream:
            subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip'],
                           stdout=stream, check=True)
        if 'sha256:' + cache_inputs.digest(archive) != artifact['digest']:
            raise ValueError('FEX artifact digest mismatch')
        # Reuse the publication tools' traversal, symlink, size and space gates.
        cache_inputs.unpack(archive, staging / 'unpacked')
        source = staging / 'unpacked'
        build = json.loads((source / 'build.json').read_text())
        if not cache_inputs.current_build(build, expected):
            raise ValueError('FEX artifact derivation or outputs do not match this commit')
        cache = source / 'cache'
        if not set(expected['outputs']) <= cache_inputs.store_paths(cache):
            raise ValueError('FEX cache omits a declared output')
        subprocess.run(['nix', 'store', 'verify', '--store', cache.as_uri(), '--all', '--no-trust'], check=True)
        subprocess.run(['nix', 'copy', '--no-check-sigs', '--from', cache.as_uri(), *expected['outputs']], check=True)
    return {'schema': 1, 'commit': commit, 'run': run['id'], 'artifact': artifact['id'],
            'artifact_digest': artifact['digest'], 'expected': expected}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    proof = import_build(commit)
    args.output.write_text(json.dumps(proof, indent=2) + '\n')
