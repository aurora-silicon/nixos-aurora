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
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts'))
import updatelib as lib  # noqa: E402

_spec = importlib.util.spec_from_file_location('collector', ROOT / 'scripts/collect-cache-inputs.py')
collector = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(collector)

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


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--previous-metadata', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
        parser.error('--repository owner/name')
    expected = collector.expected_outputs()
    covered = collector.store_paths(args.previous_metadata)
    needed = sorted(name for name, item in expected.items() if not set(item['outputs']) <= covered)
    runs = candidate_runs(args.repository) if needed else []
    action = 'publish' if needed and runs else ('missing' if needed else 'up-to-date')
    plan = {'schema': 1, 'action': action, 'head': lib.git(ROOT, 'rev-parse', 'HEAD'), 'needed': needed,
            'runs': [run['id'] for run in runs]}
    args.output.write_text(json.dumps(plan, indent=2) + '\n')
    lib.write_github_output(action=action, runs=' '.join(map(str, plan['runs'])), rebuild=' '.join(needed))
    print(f'Outputs not in the base snapshot: {", ".join(needed) or "none"}')
    print(f'Action: {action}; candidate runs: {len(runs)}')


if __name__ == '__main__':
    main()
