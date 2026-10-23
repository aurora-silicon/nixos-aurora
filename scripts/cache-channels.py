#!/usr/bin/env python3
"""Deploy the Nix binary cache and move the channel refs installed systems follow.

One cache serves every channel: it is content-addressed and cumulative, so it
holds the outputs of every commit either channel names. A channel is a Git
ref, `channel-testing` or `channel-stable`, pointing at a nixos-aurora commit
whose hardware outputs are in the live cache. channels.json on the `channels`
branch records which cache release is live and which commit each channel
serves, with history.

  assemble   authenticate a cache release for Pages and write the next state
  promote    check that a commit testing served may become stable
  record     commit the state and move the channel refs (after Pages deploy)
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts'))
import updatelib as lib  # noqa: E402

TAG = re.compile(r'cache-[A-Za-z0-9._-]+')
REFS = {'testing': 'channel-testing', 'stable': 'channel-stable'}
CACHE_URL = 'https://aurorasilicon.org/nixos-aurora/cache'


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def verify_attestation(directory, repository):
    sums = directory / 'SHA256SUMS'
    if not sums.exists():
        return 'none (snapshot predates attestations)'
    listed = {}
    for line in sums.read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        listed[name.lstrip('*')] = digest
    archive = directory / 'cache-metadata.tar.gz'
    if listed.get('cache-metadata.tar.gz') != lib.sha256_file(archive):
        raise ValueError('SHA256SUMS does not match cache-metadata.tar.gz')
    result = subprocess.run(['gh', 'attestation', 'verify', str(archive), '--repo', repository,
                             '--signer-workflow', f'{repository}/.github/workflows/publish-cache.yml',
                             '--deny-self-hosted-runners', '--format', 'json'],
                            check=True, capture_output=True, text=True)
    subjects = {(s['name'], s['digest']['sha256']) for v in json.loads(result.stdout)
                for s in v['verificationResult']['statement']['subject']}
    if not set(listed.items()) <= subjects:
        raise ValueError('the provenance attestation does not cover every snapshot asset')
    return 'verified'


def previous_commit(state, repository, tag):
    """The commit the live testing channel serves, or the newest older cache."""
    entry = state['channels'].get('testing')
    if entry and entry.get('commit'):
        return entry['commit']
    releases = lib.gh_api(f'repos/{repository}/releases?per_page=100')
    current = next(r for r in releases if r['tag_name'] == tag)
    older = sorted((r for r in releases if TAG.fullmatch(r['tag_name']) and r['created_at'] < current['created_at']),
                   key=lambda r: r['created_at'])
    return older[-1]['target_commitish'] if older else None


def pin_history(old_commit, new_commit, allow_downgrade):
    """Refuse moving any source pin to a commit older than the one served now."""
    if not old_commit or old_commit == new_commit:
        return []
    old = lib.json_at(ROOT, old_commit, 'sources.json')
    new = lib.json_at(ROOT, new_commit, 'sources.json')
    lines, downgrades = [], []
    for key in sorted(old.keys() & new.keys()):
        before, after = old[key], new[key]
        if before.get('commit') == after.get('commit'):
            continue
        try:
            same_repo = lib.repository_slug(before['repository']).lower() == lib.repository_slug(after['repository']).lower()
        except ValueError:
            same_repo = False
        if not same_repo:
            lines.append(f'{key}: moved from {before["repository"]} to {after["repository"]}')
            continue
        relation = lib.compare(lib.repository_slug(after['repository']), before['commit'], after['commit'])
        lines.append(f'{key}: {before["commit"][:12]} -> {after["commit"][:12]} ({relation["status"]})')
        if relation['status'] == 'behind':
            downgrades.append(key)
    if downgrades and not allow_downgrade:
        print('\n'.join(lines), file=sys.stderr)
        raise SystemExit('Pins would move backwards: ' + ', '.join(downgrades))
    return lines


def assemble(args):
    repository = args.repository
    if not TAG.fullmatch(args.tag):
        raise SystemExit('expected a cache-* release tag')
    state = lib.load_channels(ROOT, repository)
    site, work = Path(args.site), Path(args.work)
    download = work / 'release'
    download.mkdir(parents=True)
    lib.gh('release', 'download', args.tag, '--repo', repository, '--dir', str(download),
           '--pattern', 'cache-metadata.tar.gz', '--pattern', 'SHA256SUMS')
    provenance = verify_attestation(download, repository)
    subprocess.run([sys.executable, str(ROOT / 'scripts/extract-cache-metadata.py'),
                    str(download / 'cache-metadata.tar.gz'), str(site)], check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/verify-published-cache.py'), '--cache-dir',
                    str(site / 'cache'), '--public-key', str(ROOT / 'keys/cache.pub')], check=True)
    release = lib.gh_api(f'repos/{repository}/releases/tags/{args.tag}')
    commit = release['target_commitish']
    if not lib.HEX40.fullmatch(commit) or not lib.is_ancestor(ROOT, commit, 'origin/main'):
        raise SystemExit(f'{args.tag} does not target a commit on main')
    report = pin_history(previous_commit(state, repository, args.tag), commit, args.allow_downgrade)
    shutil.copyfile(ROOT / 'keys/cache.pub', site / 'cache.pub')
    stamp = now()
    entry = {'tag': args.tag, 'commit': commit, 'released_at': release['created_at'], 'deployed_at': stamp,
             'run_id': os.environ.get('GITHUB_RUN_ID', ''), 'actor': os.environ.get('GITHUB_ACTOR', ''),
             'provenance': provenance}
    state = json.loads(json.dumps(state))
    state['cache'] = entry
    if args.advance_testing:
        state = lib.record_channel(state, 'testing', entry)
    (site / 'channels.json').write_text(json.dumps({'repository': repository, 'cache': state['cache'],
                                                    'channels': state['channels'], 'updated_at': stamp},
                                                   indent=2, sort_keys=True) + '\n')
    (site / 'index.html').write_text(
        '<!doctype html><title>Aurora NixOS</title><h1>Aurora NixOS binary cache</h1>'
        f'<p><code>{CACHE_URL}</code>, key <code>{(ROOT / "keys/cache.pub").read_text().strip()}</code></p>\n')
    Path(args.state_out).write_text(json.dumps(state, indent=2) + '\n')
    print('\n'.join([f'## Cache {args.tag} ({commit[:12]})', '', f'- attestation: {provenance}',
                     f'- channel-testing: {"advances to " + commit[:12] if args.advance_testing else "unchanged"}',
                     '', '```', '\n'.join(report) or 'no pin changes', '```']))


def promote(args):
    repository = args.repository
    state = lib.load_channels(ROOT, repository)
    commit = args.commit or state['channels'].get('testing', {}).get('commit')
    if not commit or not lib.HEX40.fullmatch(commit):
        raise SystemExit('Nothing is on testing to promote.')
    served = lib.served_on(state, 'testing', 'commit', commit)
    if not served:
        raise SystemExit(f'{commit} has never been served on testing; promote only what testing users had.')
    first = min(item['deployed_at'] for item in served)
    soaked = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.datetime.fromisoformat(first.replace('Z', '+00:00'))).total_seconds() / 3600
    if soaked < args.min_soak_hours:
        raise SystemExit(f'{commit[:12]} has been on testing for {soaked:.1f} h; the minimum is {args.min_soak_hours} h.')
    current = state['channels'].get('stable', {}).get('commit')
    report = pin_history(current, commit, args.allow_downgrade)
    # Every hardware output of the commit must be in the live cache with a
    # valid signature, or stable systems would rebuild the kernel locally.
    expression = ('packages: builtins.concatLists (builtins.attrValues (builtins.mapAttrs (_: value: '
                  'map (name: value.${name}.outPath) value.outputs) packages))')
    paths = json.loads(subprocess.check_output(
        ['nix', 'eval', '--json', f'git+{ROOT.as_uri()}?rev={commit}#packages.aarch64-linux', '--apply', expression],
        text=True))
    subprocess.run(['nix', 'store', 'verify', '--store', args.cache_url, '--no-contents', '--sigs-needed', '1',
                    '--trusted-public-keys', (ROOT / 'keys/cache.pub').read_text().strip(), *paths], check=True)
    entry = {'commit': commit, 'tag': served[0].get('tag'), 'deployed_at': now(),
             'run_id': os.environ.get('GITHUB_RUN_ID', ''), 'actor': os.environ.get('GITHUB_ACTOR', '')}
    Path(args.state_out).write_text(json.dumps(lib.record_channel(state, 'stable', entry), indent=2) + '\n')
    print('\n'.join([f'## Stable: {current[:12] if current else "(none)"} -> {commit[:12]}', '',
                     f'{len(paths)} hardware outputs are signed in the live cache; on testing for {soaked:.1f} h.',
                     '', '```', '\n'.join(report) or 'no pin changes', '```']))


def move_ref(repository, ref, commit):
    route = f'repos/{repository}/git/refs/heads/{ref}'
    exists = lib.gh('api', route, check=False).returncode == 0
    if exists:
        lib.gh('api', '--method', 'PATCH', route, '-f', f'sha={commit}', '-F', 'force=true')
    else:
        lib.gh('api', '--method', 'POST', f'repos/{repository}/git/refs', '-f', f'ref=refs/heads/{ref}',
               '-f', f'sha={commit}')


def record(args):
    state = json.loads(Path(args.state).read_text())
    if state.get('repository') != args.repository:
        raise SystemExit('state belongs to another repository')
    for channel in args.channels:
        entry = state['channels'][channel]
        move_ref(args.repository, REFS[channel], entry['commit'])
        print(f'{REFS[channel]} -> {entry["commit"]}')
    summary = ', '.join(f'{c} {state["channels"][c]["commit"][:12]}' for c in args.channels) or 'cache only'
    lib.commit_channels(ROOT, state, f'Serve {summary}\n\nRun {os.environ.get("GITHUB_RUN_ID", "")}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY', ''))
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('assemble')
    build.add_argument('--tag', required=True)
    build.add_argument('--advance-testing', action='store_true')
    build.add_argument('--allow-downgrade', action='store_true')
    build.add_argument('--site', required=True)
    build.add_argument('--work', required=True)
    build.add_argument('--state-out', required=True)
    stable = commands.add_parser('promote')
    stable.add_argument('--commit', default='')
    stable.add_argument('--allow-downgrade', action='store_true')
    stable.add_argument('--min-soak-hours', type=float, default=0.0)
    stable.add_argument('--cache-url', default=CACHE_URL)
    stable.add_argument('--state-out', required=True)
    store = commands.add_parser('record')
    store.add_argument('--state', required=True)
    store.add_argument('--channels', nargs='*', choices=sorted(REFS), default=[])
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
        parser.error('--repository owner/name is required')
    {'assemble': assemble, 'promote': promote, 'record': record}[args.command](args)


if __name__ == '__main__':
    main()
