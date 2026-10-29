#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Import verified, unchanged hardware derivations for a native ARM image.

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


def validate_run(metadata, commit, ancestor=None):
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Expected the full image source commit')
    # Keep the existing cache producer's repository, workflow, event and
    # successful-run gates. A candidate image may reuse its own history,
    # but every imported derivation must still equal the current one below.
    cache_inputs.validate_build(metadata, ancestor or (lambda source: source == commit))


def import_build(commit, packages):
    expected = cache_inputs.expected_outputs()
    if not packages or not set(packages) <= expected.keys():
        raise ValueError('Unknown or empty image input package set')
    proofs = []
    # Routine images can use the already published, signed guest output. This
    # does not build foreign code on the ARM host or change Nix's trust policy.
    guest_available = False
    if 'fex-mesa' in packages:
        cached = subprocess.run(['nix', 'copy', '--from', 'https://aurorasilicon.org/nixos-aurora/cache',
                                 *expected['fex-mesa']['outputs']], capture_output=True, text=True)
        guest_available = cached.returncode == 0
        if guest_available:
            proofs.append({'package': 'fex-mesa', 'source': 'signed-cache', 'expected': expected['fex-mesa']})
    listing = cache_inputs.gh_json(
        f'repos/{REPOSITORY}/actions/workflows/checks.yml/runs?per_page=100')
    runs = sorted(listing['workflow_runs'], key=lambda run: run['id'], reverse=True)
    available = {}
    for run in runs:
        try:
            validate_run(run, commit, lambda source: subprocess.run(
                ['git', 'merge-base', '--is-ancestor', source, commit], cwd=ROOT,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0)
        except ValueError:
            continue
        listing = cache_inputs.gh_json(f'repos/{REPOSITORY}/actions/runs/{run["id"]}/artifacts?per_page=100')
        if listing['total_count'] > 100:
            raise ValueError('Unexpected artifact matrix size')
        for artifact in cache_inputs.newest_per_name(listing['artifacts']):
            available.setdefault(artifact['name'], (run['id'], run['head_sha'], artifact))
    for package in packages:
        if package == 'fex-mesa' and guest_available:
            continue
        found = available.get('nix-' + package + '-closure')
        if found is None:
            if package == 'fex-mesa':
                raise ValueError('Build and attest fex-mesa for this commit before building its ARM image')
            # Native outputs may come from the signed cache or a normal Nix
            # source build. Candidate imports merely avoid repeated work.
            print(f'{package}: using standard Nix substitution or source build')
            continue
        run_id, source_commit, artifact = found
        if artifact['expired'] or artifact['size_in_bytes'] > 2 * 1024**3:
            raise ValueError(f'{package}: bounded build artifact unavailable')
        with tempfile.TemporaryDirectory(prefix='aurora-image-input-') as temporary:
            staging = Path(temporary)
            archive = staging / 'artifact.zip'
            with archive.open('xb') as stream:
                subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip'],
                               stdout=stream, check=True)
            if 'sha256:' + cache_inputs.digest(archive) != artifact['digest']:
                raise ValueError(f'{package}: artifact digest mismatch')
            cache_inputs.verify_attestation(archive, source_commit)
            # Reuse the publication tools' traversal, symlink, size and space gates.
            cache_inputs.unpack(archive, staging / 'unpacked')
            source = staging / 'unpacked'
            build = json.loads((source / 'build.json').read_text())
            if not cache_inputs.current_build(build, expected[package]):
                if package == 'fex-mesa':
                    raise ValueError('Build the current fex-mesa derivation before building its ARM image')
                print(f'{package}: ignoring a stale candidate; using standard Nix substitution or source build')
                continue
            cache = source / 'cache'
            if not set(expected[package]['outputs']) <= cache_inputs.store_paths(cache):
                raise ValueError(f'{package}: cache omits a declared output')
            subprocess.run(['nix', 'store', 'verify', '--store', cache.as_uri(), '--all', '--no-trust'], check=True)
            subprocess.run(['nix', 'copy', '--no-check-sigs', '--from', cache.as_uri(), *expected[package]['outputs']], check=True)
            proofs.append({'package': package, 'run': run_id, 'source_commit': source_commit, 'artifact': artifact['id'],
                           'artifact_digest': artifact['digest'], 'expected': expected[package]})
    return {'schema': 1, 'commit': commit, 'inputs': proofs}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--packages', nargs='+', default=['fex-mesa'])
    args = parser.parse_args()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    proof = import_build(commit, args.packages)
    args.output.write_text(json.dumps(proof, indent=2) + '\n')
