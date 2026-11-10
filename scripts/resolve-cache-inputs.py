#!/usr/bin/env python3
"""List the native builds a new cache snapshot may draw from.

Evaluates the committed flake at HEAD, compares its hardware outputs with
the base snapshot's signed metadata and, if any output is new, lists the
successful checks.yml runs whose artifacts can still be downloaded, newest
first. collect-cache-inputs.py then accepts only artifacts whose derivations
equal HEAD's. Nothing is downloaded here except the base metadata.
"""
import argparse
import datetime
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts'))
import updatelib as lib  # noqa: E402

import cache_inputs as collector  # noqa: E402

RETENTION_DAYS = 90
MAX_RUNS = 60


def candidate_runs(repository, now=None, api=lib.gh_api):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    oldest = now - datetime.timedelta(days=RETENTION_DAYS)
    runs = []
    for page in range(1, 4):
        batch = api(f'repos/{repository}/actions/workflows/checks.yml/runs?status=success&per_page=100'
                    f'&page={page}').get('workflow_runs', [])
        for run in batch:
            created = datetime.datetime.fromisoformat(run['created_at'].replace('Z', '+00:00'))
            if created < oldest or run['event'] not in ('push', 'workflow_dispatch'):
                continue
            if run['event'] == 'push' and run['head_branch'] != 'main':
                continue
            if lib.is_ancestor(ROOT, run['head_sha']):
                runs.append(run)
        if len(batch) < 100:
            break
    runs.sort(key=lambda run: (run['created_at'], run['id']), reverse=True)
    return runs[:MAX_RUNS]


def publication_plan(expected, covered, head, previous_commit, served_commit, runs, *, ancestor):
    needed = sorted(name for name, item in expected.items() if not set(item['outputs']) <= covered)
    if any(commit and commit != head and not ancestor(commit, head)
           for commit in (previous_commit, served_commit)):
        # A queued workflow must not roll a newer published/served module set
        # back merely because both commits happen to share hardware outputs.
        action = 'up-to-date'
    elif needed:
        action = 'publish' if runs else 'missing'
    else:
        action = 'reuse' if previous_commit != head else ('up-to-date' if served_commit == head else 'deploy')
    return {'schema': 1, 'action': action, 'head': head, 'needed': needed, 'runs': list(runs)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--previous-metadata', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--previous-commit', required=True)
    parser.add_argument('--build-runs', nargs='*', default=[])
    parser.add_argument('--served-commit', default='')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
        parser.error('--repository owner/name')
    if not re.fullmatch('[a-f0-9]{40}', args.previous_commit):
        parser.error('--previous-commit must be a full Git commit')
    if any(not re.fullmatch('[0-9]+', run) for run in args.build_runs):
        parser.error('--build-runs must contain numeric workflow run IDs')
    if args.served_commit and not re.fullmatch('[a-f0-9]{40}', args.served_commit):
        parser.error('--served-commit must be a full Git commit')
    expected = collector.expected_outputs()
    covered = collector.store_paths(args.previous_metadata)
    head = lib.git(ROOT, 'rev-parse', 'HEAD')
    needed = any(not set(item['outputs']) <= covered for item in expected.values())
    runs = args.build_runs or ([run['id'] for run in candidate_runs(args.repository)] if needed else [])
    plan = publication_plan(expected, covered, head, args.previous_commit, args.served_commit, runs,
                            ancestor=lambda before, after: lib.is_ancestor(ROOT, before, after))
    args.output.write_text(json.dumps(plan, indent=2) + '\n')
    lib.write_github_output(action=plan['action'], runs=' '.join(map(str, plan['runs'])), rebuild=' '.join(plan['needed']))
    print(f'Outputs not in the base snapshot: {", ".join(plan['needed']) or "none"}')
    print(f'Action: {plan["action"]}; candidate runs: {len(runs)}')


if __name__ == '__main__':
    main()
