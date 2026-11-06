#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify image contents and trust, using this job's authenticated import proof.

The importer emits the proof only after artifact digest, provenance, source,
derivation and complete NAR checks. Candidate hashes retain that admission;
all other paths still require Nix signatures or local build ownership.
The proof must come from this job's importer; it is not a standalone token
for authenticating externally supplied proofs and grants no published trust.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cache_inputs import NAR_HASH, STORE_PATH, nar_hashes  # noqa: E402


def ordinary_paths(proof, commit, actual):
    if (proof.get('schema') != 1 or proof.get('commit') != commit
            or not re.fullmatch('[a-f0-9]{40}', commit)
            or not isinstance(proof.get('narHashes'), dict)):
        raise ValueError('Expected this job\'s current authenticated import proof')
    admitted = proof['narHashes']
    for path, value in admitted.items():
        if not STORE_PATH.fullmatch(path) or not isinstance(value, str) or not NAR_HASH.fullmatch(value):
            raise ValueError('Invalid authenticated NAR identity')
        if path in actual and actual[path] != value:
            raise ValueError('An imported NAR no longer matches its authenticated hash: ' + path)
    return sorted(actual.keys() - admitted.keys())


def verify(roots, proof, commit):
    actual = nar_hashes(json.loads(subprocess.check_output(
        ['nix', 'path-info', '--json', '--recursive', *roots], text=True)))
    ordinary = ordinary_paths(proof, commit, actual)
    # Check every byte, including the imported candidates, against the store's
    # NAR identity. The comparison above also anchors imports to their proof.
    subprocess.run(['nix', 'store', 'verify', '--recursive', '--no-trust', *roots], check=True)
    # Check the complete remaining closure without recursing back into the
    # candidates whose exact hashes already have verified build provenance.
    for offset in range(0, len(ordinary), 250):
        subprocess.run(['nix', 'store', 'verify', *ordinary[offset:offset + 250]], check=True)
    print(f'Image closure verified: {len(actual)} NARs; '
          f'{len(actual) - len(ordinary)} authenticated imports; '
          f'{len(ordinary)} paths checked with normal Nix trust')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proof', type=Path, required=True)
    parser.add_argument('roots', nargs='+')
    args = parser.parse_args()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    verify(args.roots, json.loads(args.proof.read_text()), commit)
