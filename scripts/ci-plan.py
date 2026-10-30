#!/usr/bin/env python3
"""Build changed Nix outputs using immutable, tracked-only Git flake inputs."""
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def select(current, previous=None, requested=()):
    if requested:
        if not set(requested) <= current.keys():
            raise ValueError('Unknown requested hardware output')
        return sorted(set(requested))
    if previous is None:
        return sorted(current)
    return sorted(name for name, path in current.items() if previous.get(name) != path)


def derivations(commit):
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Expected a full Git commit')
    reference = 'git+' + ROOT.as_uri() + '?rev=' + commit
    return json.loads(subprocess.check_output([
        'nix', 'eval', '--json', reference + '#packages.aarch64-linux',
        '--apply', 'outputs: builtins.mapAttrs (_: value: value.drvPath) outputs',
    ], text=True))


def main():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    current = derivations(os.environ['GITHUB_SHA'])
    requested = event.get('inputs', {}).get('packages', '').split()
    previous = None
    before = event.get('before', '')
    if not requested:
        if (os.environ['GITHUB_EVENT_NAME'] == 'pull_request'
                or os.environ.get('GITHUB_REF', '').startswith('refs/heads/ci/')
                or not before.strip('0')):
            before = subprocess.check_output(['git', 'merge-base', 'HEAD', 'origin/main'], text=True).strip()
        previous = derivations(before)
    print('packages=' + json.dumps(select(current, previous, requested)))


if __name__ == '__main__':
    main()
