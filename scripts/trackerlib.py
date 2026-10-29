#!/usr/bin/env python3
"""Source-pin tracking shared by the Aurora distribution repositories.

Copied verbatim into alarm-aurora, fedora-aurora and nixos-aurora; each
repository's scripts/track-sources.py supplies only the recipe adapter.

The tracker runs in two privilege levels. `plan` needs only read access: it
resolves branch tips, downloads and verifies source archives, edits a
checkout, runs the repository's checks and writes a patch plus a result
record. `open-pr` and `merge` apply that record with a write-scoped token and
never execute fetched source code. No step reads signing keys.
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import updatelib as lib  # noqa: E402

MARKER = 'aurora-track-sources'
BOT_NAME = 'github-actions[bot]'
BOT_EMAIL = '41898282+github-actions[bot]@users.noreply.github.com'
MIRROR_TAG = 'source-cache'
MERGE_POLICIES = ('auto', 'auto-same-version', 'manual')


# ------------------------------------------------------------------ configuration

def load_tracking(root):
    data = json.loads((Path(root) / 'tracking.json').read_text())
    if data.get('schema') != 1 or not isinstance(data.get('sources'), dict):
        raise ValueError('tracking.json must be schema 1 with a sources map')
    if not re.fullmatch(r'auto/[a-z0-9-]+', data.get('branch', '')):
        raise ValueError('the tracking branch must be under auto/')
    for key, entry in data['sources'].items():
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', entry.get('repository', '')):
            raise ValueError(f'{key}: repository must be owner/name')
        if not entry.get('branch') or entry.get('merge') not in MERGE_POLICIES:
            raise ValueError(f'{key}: branch and a merge policy are required')
    return data


def load_pins(root):
    return json.loads((Path(root) / 'sources.json').read_text())


def edit_pins_text(text, pins):
    """Rewrite only the changed values in sources.json, keeping its layout."""
    original = json.loads(text)
    for key, pin in pins.items():
        if original.get(key) == pin:
            continue
        if key not in original:
            raise ValueError(f'{key}: the tracker only updates existing pins')
        start = text.index(json.dumps(key) + ':')
        open_at = text.index('{', start)
        close_at = text.index('}', open_at)
        block = text[open_at:close_at]
        for field, value in pin.items():
            if original[key].get(field) == value:
                continue
            if field in original[key]:
                pattern = re.compile(re.escape(json.dumps(field)) + r'(\s*:\s*)' + re.escape(json.dumps(original[key][field])))
                if len(pattern.findall(block)) != 1:
                    raise ValueError(f'{key}.{field}: not found exactly once in sources.json')
                block = pattern.sub(lambda m: json.dumps(field) + m[1] + json.dumps(value), block)
            else:
                indent = re.search(r'\n([ \t]+)"', block)[1]
                block = block.rstrip() + f',\n{indent}{json.dumps(field)}: {json.dumps(value)}\n' + indent[:-2]
        text = text[:open_at] + block + text[close_at:]
    if json.loads(text) != pins:
        raise ValueError('sources.json edit did not produce the intended pins')
    return text


def write_pins(root, pins):
    path = Path(root) / 'sources.json'
    path.write_text(edit_pins_text(path.read_text(), pins))


def mirror_url(repository, filename):
    return f'https://github.com/{repository}/releases/download/{MIRROR_TAG}/{filename}'


def archive_filename(key, commit, pin=None):
    """Mirror asset name; matches the file name source fetchers use."""
    if pin and pin.get('archive_file'):
        return pin['archive_file']
    return f'{key}-{commit}.tar.gz'


# ---------------------------------------------------------------------- planning

def plan(root, tracking, pins, resolve=lib.branch_tip, compare=lib.compare):
    """Decide, per tracked source, whether its pin should move."""
    items = []
    for key, entry in sorted(tracking['sources'].items()):
        pin = pins.get(key)
        item = {'key': key, 'repository': entry['repository'], 'branch': entry['branch'],
                'merge': entry['merge']}
        if pin is None:
            items.append({**item, 'status': 'not-pinned'})
            continue
        pinned_slug = lib.repository_slug(pin['repository'])
        item['old'] = pin['commit']
        if pinned_slug.lower() != entry['repository'].lower():
            # Moving to another repository is a reviewed recipe change.
            items.append({**item, 'status': 'repository-switch-required', 'pinned_repository': pinned_slug})
            continue
        tip = resolve(entry['repository'], entry['branch'])
        item.update(new=tip['sha'], new_date=tip['date'], new_subject=tip['subject'])
        if tip['sha'] == pin['commit']:
            items.append({**item, 'status': 'current'})
            continue
        relation = compare(entry['repository'], pin['commit'], tip['sha'], branch=entry['branch'])
        item['compare'] = relation
        if relation['status'] == 'ahead':
            items.append({**item, 'status': 'update'})
        elif relation['status'] == 'diverged':
            # The branch was rewritten. Propose it, but a person decides.
            items.append({**item, 'status': 'update', 'rewritten': True})
        else:
            items.append({**item, 'status': 'pin-ahead-of-branch'})
    return items


def prepare_source(item, workdir, repository, token=None, download=lib.download):
    """Download, verify and describe the new archive for one source."""
    key, slug, commit = item['key'], item['repository'], item['new']
    filename = archive_filename(key, commit)
    path = Path(workdir) / filename
    urls = [mirror_url(repository, filename), lib.codeload_url(slug, commit)]
    used = download(urls, path, token=token)
    digest = lib.sha256_file(path)
    info = {'path': str(path), 'filename': filename, 'downloaded_from': used, 'sha256': digest,
            'nix_hash': lib.sri_from_hex(digest), 'archive_root': lib.archive_root(path),
            'source_url': lib.codeload_url(slug, commit)}
    comment = lib.archive_commit_comment(path)
    if comment and comment != commit:
        raise ValueError(f'{key}: archive header names {comment}, not {commit}')
    expected_tree = lib.commit_tree(slug, commit)
    actual_tree = lib.git_tree_of_archive(path)
    info['tree'] = expected_tree
    info['tree_verified'] = actual_tree == expected_tree
    if not info['tree_verified']:
        # export-ignore rules hide themselves from archives, so a mismatch is
        # not proof of tampering; it withholds automatic merging instead.
        info['tree_note'] = ('archive tree could not be reconstructed' if actual_tree is None
                             else f'archive tree {actual_tree} differs from the commit tree')
    return info


def upstream_version(kind, archive):
    """(pinned, raw) versions. sources.json records the kernel's full release
    (7.3.0, 7.4.0-rc1) and Mesa's numeric release (26.3.0 for 26.3.0-devel)."""
    if kind == 'kernel':
        found = lib.read_members(archive, ['Makefile'])
        raw = lib.kernel_version(found['Makefile'].decode())
        return raw, raw
    if kind == 'mesa':
        found = lib.read_members(archive, ['VERSION'])
        raw = lib.mesa_version(found['VERSION'].decode())
        return raw.split('-', 1)[0], raw
    return None, None


def update_pin(pins, key, item, info, *, version=None, nix=False):
    pin = dict(pins[key])
    pin.update(commit=item['new'], source_url=info['source_url'], archive_root=info['archive_root'],
               sha256=info['sha256'])
    if version:
        pin['version'] = version
    if nix or 'nix_hash' in pin:
        pin['nix_hash'] = info['nix_hash']
    pins[key] = pin
    return pin


# ------------------------------------------------------------------ recipe edits

def replace_commit(text, old, new):
    """Replace a full commit and any abbreviated (>= 7) forms of it."""
    if not (lib.HEX40.fullmatch(old) and lib.HEX40.fullmatch(new)):
        raise ValueError('commit IDs must be full SHA-1s')
    text = text.replace(old, new)

    def short(match):
        value = match[0]
        return new[:len(value)] if old.startswith(value) else value

    return re.sub(r'(?<![0-9a-f])[0-9a-f]{7,39}(?![0-9a-f])', short, text)


def bump_assignment(text, name, transform):
    pattern = re.compile(rf'^({re.escape(name)}=)(\S+)$', re.M)
    match = pattern.search(text)
    if not match:
        raise ValueError(f'{name}= not found')
    value = transform(match[2])
    return pattern.sub(lambda m: m[1] + value, text, count=1), match[2], value


def spec_field(text, name):
    match = re.search(rf'^{name}:\s*(\S+)\s*$', text, re.M)
    if not match:
        raise ValueError(f'{name}: not found')
    return match[1]


def set_spec_field(text, name, value):
    return re.sub(rf'^({name}:\s*)\S+(\s*)$', lambda m: m[1] + value + m[2], text, count=1, flags=re.M)


def bump_spec_release(text, reset):
    release = spec_field(text, 'Release')
    match = re.fullmatch(r'(\d+)(.*)', release)
    if not match:
        raise ValueError('Release must start with a number')
    number = 1 if reset else int(match[1]) + 1
    return set_spec_field(text, 'Release', f'{number}{match[2]}'), number


def add_spec_changelog(text, version, release, lines, today, author='Aurora Silicon <hey@djdev.me>'):
    if '\n%changelog\n' not in text:
        raise ValueError('spec has no %changelog')
    stamp = today.strftime('%a %b %d %Y')
    entry = f'* {stamp} {author} - {version}-{release}\n' + ''.join(f'- {line}\n' for line in lines) + '\n'
    return text.replace('\n%changelog\n', '\n%changelog\n' + entry, 1)


def rpm_version(upstream):
    """RPM-safe upstream version: 7.3.0-rc1 -> 7.3.0~rc1, 26.3.0-devel -> 26.3.0."""
    base, _, extra = upstream.partition('-')
    if extra in ('', 'devel'):
        return base
    return f'{base}~{extra}'


def pacman_version(upstream):
    """pacman-safe upstream version (no hyphens): 7.3.0-rc1 -> 7.3.0rc1."""
    return upstream.replace('-', '')


def file_digest_text(path):
    return lib.sha256_file(path) if Path(path).exists() else None


def refresh_pkgbuild_checksums(directory, before):
    """Replace sha256sums of local sources whose bytes changed."""
    pkgbuild = Path(directory) / 'PKGBUILD'
    text = pkgbuild.read_text()
    for name, old_digest in before.items():
        new_digest = lib.sha256_file(Path(directory) / name)
        if old_digest != new_digest:
            if text.count(old_digest) != 1:
                raise ValueError(f'{name}: its checksum is not recorded exactly once in PKGBUILD')
            text = text.replace(old_digest, new_digest)
    pkgbuild.write_text(text)


def cargo_git_sources(lock_text):
    return sorted(set(re.findall(r'^source = "(git\+[^"]+)"$', lock_text, re.M)))


# --------------------------------------------------------------------- UAPI check

def fetch_uapi(slug, commit, directory, destination):
    listing = lib.gh_api(f'repos/{slug}/contents/{directory}?ref={commit}')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for entry in listing:
        if entry['type'] == 'file' and entry['name'].endswith('.h'):
            data = lib.gh('api', '-H', 'Accept: application/vnd.github.raw',
                          f'repos/{slug}/contents/{directory}/{entry["name"]}?ref={commit}').stdout
            (destination / entry['name']).write_text(data)
    return destination


def uapi_check(pins, kernel_key='kernel-aurora', mesa_key='mesa-aurora', workdir=None):
    kernel, mesa = pins[kernel_key], pins[mesa_key]
    with tempfile.TemporaryDirectory(prefix='aurora-uapi-', dir=workdir) as temporary:
        k = fetch_uapi(lib.repository_slug(kernel['repository']), kernel['commit'], 'include/uapi/drm',
                       Path(temporary) / 'kernel')
        m = fetch_uapi(lib.repository_slug(mesa['repository']), mesa['commit'], 'include/drm-uapi',
                       Path(temporary) / 'mesa')
        # Newer kernel UAPI headers include linux/bits.h and linux/const.h,
        # which an older system linux-libc-dev lacks; the kernel's own copies
        # are used only where the system has none.
        compat = Path(temporary) / 'compat'
        slug = lib.repository_slug(kernel['repository'])
        for name in ('bits.h', 'const.h'):
            result = lib.gh('api', '-H', 'Accept: application/vnd.github.raw',
                            f'repos/{slug}/contents/include/uapi/linux/{name}?ref={kernel["commit"]}', check=False)
            if result.returncode == 0:
                (compat / 'linux').mkdir(parents=True, exist_ok=True)
                (compat / 'linux' / name).write_text(result.stdout)
        report = lib.uapi_report(k, m, extra_includes=[compat])
    report['kernel'] = kernel['commit']
    report['mesa'] = mesa['commit']
    return report


# -------------------------------------------------------------------- decisions

def merge_decision(items, uapi):
    """Whether CI success alone may merge this proposal, with reasons."""
    reasons = []
    for item in items:
        if item.get('status') != 'update':
            continue
        if item['merge'] == 'manual':
            reasons.append(f'{item["key"]}: merge policy is manual')
        if item.get('rewritten'):
            reasons.append(f'{item["key"]}: upstream history was rewritten')
        if item['merge'] == 'auto-same-version' and item.get('version_changed'):
            reasons.append(f'{item["key"]}: upstream version changed to {item.get("version")}')
        if not item.get('tree_verified'):
            reasons.append(f'{item["key"]}: archive could not be proven equal to the commit tree')
        if item.get('needs_review'):
            reasons.extend(f'{item["key"]}: {reason}' for reason in item['needs_review'])
    if uapi is not None and not uapi.get('compatible'):
        reasons.append('GPU UAPI conflicts between the kernel and Mesa pins')
    return not reasons, reasons


def summary_markdown(repository, items, uapi, auto, reasons, packages):
    lines = ['Automated source update proposed by `track-sources.yml`.', '',
             '| Source | Branch | From | To | Status |', '|---|---|---|---|---|']
    for item in items:
        old = item.get('old', '')[:12]
        new = item.get('new', '')[:12]
        link = (f'[{old}…{new}](https://github.com/{item["repository"]}/compare/{item["old"]}...{item["new"]})'
                if item.get('status') == 'update' else new or '-')
        lines.append(f'| `{item["key"]}` | `{item["repository"]}` `{item["branch"]}` | `{old}` | {link} | '
                     f'{item["status"]}{" (rewritten)" if item.get("rewritten") else ""} |')
    for item in items:
        if item.get('status') != 'update':
            continue
        lines += ['', f'### {item["key"]}', '',
                  f'- Commit `{item["new"]}` ({item.get("new_date", "")}): {item.get("new_subject", "")}',
                  f'- Archive SHA-256 `{item["sha256"]}`, Nix `{item["nix_hash"]}`',
                  f'- Archive root `{item["archive_root"]}`; Git tree '
                  + (f'`{item["tree"]}` verified' if item.get('tree_verified') else 'not verifiable'),
                  ]
        if item.get('version'):
            lines.append(f'- Upstream version `{item["version"]}`'
                         + (' (changed)' if item.get('version_changed') else ''))
        for note in item.get('notes', []):
            lines.append(f'- {note}')
        commits = item.get('compare', {}).get('commits', [])
        if commits:
            lines += ['', '<details><summary>Commits</summary>', '']
            lines += [f'- `{c["sha"][:12]}` {c["subject"]}' for c in commits]
            lines += ['', '</details>']
    if uapi is not None:
        lines += ['', '### GPU UAPI', '',
                  f'Kernel `{uapi["kernel"][:12]}` against Mesa `{uapi["mesa"][:12]}`: '
                  + ('compatible' if uapi['compatible'] else '**conflicting**')
                  + f' ({uapi["compared"]["constants"]} constants, {uapi["compared"]["structs"]} records compared).']
        lines += [f'- conflict: {c}' for c in uapi['conflicts']]
        lines += [f'- note: {n}' for n in uapi['notes'][:20]]
        if uapi['mesa_only']:
            lines.append('- Mesa-only definitions: ' + ', '.join(f'`{n}`' for n in uapi['mesa_only'][:20]))
    lines += ['', '### Merge', '']
    if auto:
        lines.append('Eligible for automatic merge once every CI run below succeeds and '
                     '`AUTO_MERGE_SOURCES` is `true`.')
    else:
        lines.append('Needs a maintainer:')
        lines += [f'- {reason}' for reason in reasons]
    lines += ['', f'CI dispatched for: {", ".join(f"`{p}`" for p in packages) or "none"}.']
    return '\n'.join(lines) + '\n'


# --------------------------------------------------------------- GitHub actions

def open_pr(repository, branch):
    pulls = lib.gh_api(f'repos/{repository}/pulls?state=open&head={repository.split("/")[0]}:{branch}')
    return pulls[0] if pulls else None


def pr_record(pr):
    """The machine-readable record the tracker embedded in a PR body."""
    match = re.search(rf'<!-- {MARKER} (\{{.*?\}}) -->', (pr or {}).get('body') or '', re.S)
    return json.loads(match[1]) if match else None


def ci_state(repository, sha, workflows):
    """Combined state of the required workflow runs for one commit."""
    runs = lib.gh_api(f'repos/{repository}/actions/runs?head_sha={sha}&per_page=100')['workflow_runs']
    states = {}
    for workflow in workflows:
        path = f'.github/workflows/{workflow}'
        candidates = sorted((run for run in runs if run['path'] == path),
                            key=lambda run: (run['created_at'], run['id']))
        if not candidates:
            states[workflow] = 'missing'
            continue
        latest = candidates[-1]
        if latest['status'] != 'completed':
            states[workflow] = 'pending'
        else:
            states[workflow] = 'success' if latest['conclusion'] == 'success' else 'failure'
    if any(state == 'failure' for state in states.values()):
        overall = 'failure'
    elif any(state in ('pending', 'missing') for state in states.values()):
        overall = 'pending'
    else:
        overall = 'success'
    return overall, states


def main_head(repository):
    return lib.gh_api(f'repos/{repository}/commits/main')['sha']


def head_commit_is_bot(repository, sha):
    commit = lib.gh_api(f'repos/{repository}/commits/{sha}')
    author = (commit.get('author') or {}).get('login', '')
    committer = (commit.get('committer') or {}).get('login', '')
    return author == BOT_NAME and committer in (BOT_NAME, 'web-flow')


def ensure_mirror_release(repository):
    result = lib.gh('release', 'view', MIRROR_TAG, '--repo', repository, '--json', 'assets', check=False)
    if result.returncode == 0:
        return {asset['name']: asset for asset in json.loads(result.stdout)['assets']}
    lib.gh('release', 'create', MIRROR_TAG, '--repo', repository, '--prerelease', '--latest=false',
           '--title', 'Verified source archive cache',
           '--notes', 'Upstream source archives whose SHA-256 matches sources.json. Builds verify every '
                      'byte against the pinned hash, so this cache only avoids rate-limited downloads.')
    return {}


def upload_mirror(repository, files):
    existing = ensure_mirror_release(repository)
    for path in files:
        path = Path(path)
        if path.name in existing:
            continue
        lib.gh('release', 'upload', MIRROR_TAG, str(path), '--repo', repository)


def dispatch(repository, workflow, ref, inputs=None):
    args = ['workflow', 'run', workflow, '--repo', repository, '--ref', ref]
    for name, value in (inputs or {}).items():
        args += ['-f', f'{name}={value}']
    lib.gh(*args)


def today():
    return datetime.datetime.now(datetime.timezone.utc).date()


# ---------------------------------------------------------------------- commands

ROOT = Path(__file__).resolve().parents[1]
STALE_PENDING_SECONDS = 6 * 3600


def _age_seconds(timestamp):
    when = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    return (datetime.datetime.now(datetime.timezone.utc) - when).total_seconds()


def _commit_message(result):
    lines = [result['title'], '']
    for item in result['items']:
        if item.get('status') != 'update':
            continue
        lines.append(f'Move {item["key"]} from {item["old"]} to {item["repository"]} '
                     f'{item["branch"]} {item["new"]}.')
        lines.append(f'Archive SHA-256 {item["sha256"]}, Nix {item["nix_hash"]}.')
        if item.get('package_version'):
            lines.append(f'Package version {item["package_version"]}.')
        lines.append('')
    lines.append('Generated by track-sources.yml from verified upstream archives.')
    return '\n'.join(lines) + '\n'


def open_pr_command(args, workflows):
    """Commit a planned update to the bot branch and dispatch its CI."""
    repository = args.repository
    tracking = load_tracking(ROOT)
    branch = tracking['branch']
    source = Path(args.input)
    result = json.loads((source / 'result.json').read_text())
    if result.get('schema') != 1 or result.get('repository') != repository:
        raise SystemExit('the plan belongs to another repository')
    pr = open_pr(repository, branch)
    record = pr_record(pr)
    if pr and (not record or record.get('head') != pr['head']['sha']
               or not head_commit_is_bot(repository, pr['head']['sha'])):
        lib.log(f'PR #{pr["number"]} was changed by a maintainer; the tracker leaves it alone.')
        return
    if not result['changes']:
        if pr:
            lib.gh('pr', 'close', str(pr['number']), '--repo', repository, '--delete-branch',
                   '--comment', 'Every tracked pin on main is current; closing this proposal.')
        lib.log('All tracked sources are current.')
        return
    targets = {item['key']: item['new'] for item in result['items'] if item.get('status') == 'update'}
    if pr and record.get('targets') == targets and record.get('base') == result['base']:
        lib.log(f'PR #{pr["number"]} already proposes these commits.')
        return
    if pr and not args.force:
        state, _ = ci_state(repository, pr['head']['sha'], workflows)
        if state == 'pending' and _age_seconds(pr['updated_at']) < STALE_PENDING_SECONDS:
            lib.log(f'PR #{pr["number"]} CI is still running; it will be refreshed afterwards.')
            return
    lib.git(ROOT, 'fetch', '--quiet', 'origin', 'main')
    main = lib.git(ROOT, 'rev-parse', 'origin/main')
    if main != result['base']:
        lib.log(f'main moved from {result["base"]} to {main} after planning; the next run replans.')
        return
    patch = source / 'changes.patch'
    check_patch_paths(patch, result['paths'])
    lib.git(ROOT, 'checkout', '--quiet', '-B', branch, main)
    subprocess.run(['git', '-C', str(ROOT), 'apply', '--index', '--whitespace=nowarn', str(patch.resolve())],
                   check=True)
    message = source / 'commit-message.txt'
    message.write_text(_commit_message(result))
    subprocess.run(['git', '-C', str(ROOT), '-c', f'user.name={BOT_NAME}', '-c', f'user.email={BOT_EMAIL}',
                    'commit', '--quiet', '--file', str(message.resolve())], check=True)
    head = lib.git(ROOT, 'rev-parse', 'HEAD')
    # Archives first: CI may fetch them from the mirror as soon as it starts.
    archives = sorted((source / 'sources').glob('*.tar.gz'))
    if archives:
        pins = load_pins(ROOT)
        expected = {archive_filename(key, pin['commit'], pin): pin['sha256'] for key, pin in pins.items()
                    if 'sha256' in pin}
        verified = [path for path in archives if expected.get(path.name) == lib.sha256_file(path)]
        upload_mirror(repository, verified)
    subprocess.run(['git', '-C', str(ROOT), 'push', '--quiet', '--force', 'origin', f'HEAD:refs/heads/{branch}'],
                   check=True)
    record = {'head': head, 'base': main, 'targets': targets, 'auto_merge': result['auto_merge'],
              'reasons': result['reasons'], 'ci': result['ci']}
    body = (source / 'summary.md').read_text() + f'\n<!-- {MARKER} {json.dumps(record, sort_keys=True)} -->\n'
    body_file = source / 'pr-body.md'
    body_file.write_text(body)
    if pr:
        lib.gh('pr', 'edit', str(pr['number']), '--repo', repository, '--title', result['title'],
               '--body-file', str(body_file))
        number = pr['number']
    else:
        created = lib.gh('pr', 'create', '--repo', repository, '--base', 'main', '--head', branch,
                         '--title', result['title'], '--body-file', str(body_file)).stdout.strip()
        number = created.rsplit('/', 1)[-1]
    for workflow, inputs in result['ci'].items():
        dispatch(repository, workflow, branch, {k: v for k, v in inputs.items() if v != ''})
    for workflow in workflows:
        if workflow not in result['ci']:
            dispatch(repository, workflow, branch)
    lib.log(f'PR #{number} proposes {head}; CI dispatched for {", ".join(workflows)}.')


def merge_command(args, workflows):
    """Merge the bot's proposal once its exact head passed every CI run."""
    repository = args.repository
    branch = load_tracking(ROOT)['branch']
    pr = open_pr(repository, branch)
    if not pr:
        lib.log('No open source-tracking PR.')
        return
    record = pr_record(pr)
    head = pr['head']['sha']
    if not record or record.get('head') != head or not head_commit_is_bot(repository, head):
        lib.log(f'PR #{pr["number"]} head is not the tracker\'s recorded commit; a maintainer decides.')
        return
    # CI ran on the proposal as planned on record['base']. If main has moved
    # since, a change that landed in between (a new lockstep recipe, say) was
    # never checked against it: leave the merge to the next plan, which
    # replans on the new main and refreshes the PR.
    main = main_head(repository)
    if record.get('base') != main:
        lib.log(f'PR #{pr["number"]} was planned on {record.get("base")} but main is {main}; '
                'the next run replans it.')
        return
    state, states = ci_state(repository, head, workflows)
    lib.log(f'PR #{pr["number"]} CI: {state} {states}')
    if state != 'success':
        return
    if not record.get('auto_merge'):
        lib.log('Automatic merge withheld: ' + '; '.join(record.get('reasons', [])))
        return
    if os.environ.get('AUTO_MERGE_SOURCES') != 'true':
        lib.log('CI passed. Automatic merging is disabled (repository variable AUTO_MERGE_SOURCES).')
        return
    if args.dry_run:
        lib.log(f'Dry run: would merge PR #{pr["number"]} at {head}.')
        return
    # A merge commit keeps the dispatched CI build an ancestor of main, so the
    # publisher can reuse its artifacts.
    lib.gh('pr', 'merge', str(pr['number']), '--repo', repository, '--merge', '--delete-branch',
           '--match-head-commit', head)
    lib.log(f'Merged PR #{pr["number"]} at {head}.')
    if args.publish_workflow:
        dispatch(repository, args.publish_workflow, 'main')
        lib.log(f'Dispatched {args.publish_workflow} on main.')


MIRROR_KEEP_DAYS = 90


def mirror_command(args, adapter=None):
    """Ensure every pinned archive is in the verified source cache."""
    repository = args.repository
    pins = load_pins(ROOT)
    wanted = {}
    for key, pin in sorted(pins.items()):
        if pin.get('sha256') and pin.get('source_url') and pin.get('commit'):
            wanted[archive_filename(key, pin['commit'], pin)] = pin
    # Archives pinned outside sources.json (adapter.extra_archives()).
    extra = getattr(adapter, 'extra_archives', None)
    for name, (url, digest) in (extra() if extra else {}).items():
        wanted[name] = {'source_url': url, 'sha256': digest}
    if args.dry_run:
        result = lib.gh('release', 'view', MIRROR_TAG, '--repo', repository, '--json', 'assets', check=False)
        existing = {a['name']: a for a in json.loads(result.stdout)['assets']} if result.returncode == 0 else {}
    else:
        existing = ensure_mirror_release(repository)
    with tempfile.TemporaryDirectory(prefix='aurora-mirror-') as temporary:
        for name, pin in wanted.items():
            asset = existing.get(name)
            if asset:
                digest = (asset.get('digest') or '').removeprefix('sha256:')
                if digest and digest != pin['sha256']:
                    raise SystemExit(f'Mirror asset {name} has digest {digest}, not the pinned {pin["sha256"]}')
                continue
            if args.dry_run:
                lib.log(f'Would mirror {name}')
                continue
            path = Path(temporary) / name
            lib.download([pin['source_url']], path, sha256=pin['sha256'], token=os.environ.get('GH_TOKEN'))
            lib.gh('release', 'upload', MIRROR_TAG, str(path), '--repo', repository)
            path.unlink()
            lib.log(f'Mirrored {name}')
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=MIRROR_KEEP_DAYS)
    for name, asset in existing.items():
        created = datetime.datetime.fromisoformat(asset['createdAt'].replace('Z', '+00:00')) if asset.get('createdAt') else None
        if name not in wanted and created and created < cutoff:
            if args.dry_run:
                lib.log(f'Would prune {name}')
            else:
                lib.gh('release', 'delete-asset', MIRROR_TAG, name, '--repo', repository, '--yes')


def main(adapter):
    workflows = adapter.CI_WORKFLOWS
    plan_command = lambda args: run_plan(args, adapter)  # noqa: E731
    import argparse
    parser = argparse.ArgumentParser(description='Track upstream source branches.')
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY', ''))
    commands = parser.add_subparsers(dest='command', required=True)
    planner = commands.add_parser('plan', help='resolve tips, verify archives and prepare a patch (read-only)')
    planner.add_argument('--output', required=True)
    planner.add_argument('--today', help='override the UTC date used in package versions (YYYY-MM-DD)')
    opener = commands.add_parser('open-pr', help='commit a plan to the bot branch, open the PR and run CI')
    opener.add_argument('--input', required=True)
    opener.add_argument('--force', action='store_true', help='refresh even while CI is running')
    merger = commands.add_parser('merge', help='merge the bot PR when its CI has passed')
    merger.add_argument('--dry-run', action='store_true')
    merger.add_argument('--publish-workflow', default='publish.yml')
    mirror = commands.add_parser('mirror', help='upload every pinned archive to the verified source cache')
    mirror.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
        parser.error('--repository owner/name is required')
    if args.command == 'plan':
        plan_command(args)
    elif args.command == 'open-pr':
        open_pr_command(args, workflows)
    elif args.command == 'mirror':
        mirror_command(args, adapter)
    else:
        merge_command(args, workflows)


def run_plan(args, adapter):
    """Shared `plan` command. `adapter` supplies, per repository:
    RECIPES {source key: package name}, KINDS {source key: kernel|mesa},
    update_recipe(root, item, today) -> notes, run_checks(root) and
    ci_inputs(packages) -> {workflow: inputs}.
    """
    root = ROOT
    tracking = load_tracking(root)
    pins = load_pins(root)
    output = Path(args.output)
    if output.exists():
        raise SystemExit('use a new output directory')
    (output / 'sources').mkdir(parents=True)
    items = plan(root, tracking, pins)
    token = os.environ.get('GH_TOKEN')
    today_ = datetime.date.fromisoformat(args.today) if args.today else today()
    updated = []
    for item in items:
        if item['status'] != 'update':
            continue
        info = prepare_source(item, output / 'sources', args.repository, token=token)
        item.update({k: v for k, v in info.items() if k != 'path'})
        item['archive_path'] = info['path']
        item['previous_version'] = pins[item['key']].get('version')
        kind = adapter.KINDS.get(item['key'])
        if kind:
            item['version'], item['upstream_version'] = upstream_version(kind, info['path'])
            item['version_changed'] = item['version'] != pins[item['key']].get('version')
        if info.get('tree_note'):
            item.setdefault('notes', []).append(info['tree_note'])
        update_pin(pins, item['key'], item, info, version=item.get('version'),
                   nix=getattr(adapter, 'NIX', False))
        updated.append(item)
    if updated:
        write_pins(root, pins)
        for item in updated:
            item.setdefault('notes', []).extend(adapter.update_recipe(root, item, today_))
        adapter.run_checks(root)
    uapi = None
    if {'kernel-aurora', 'mesa-aurora'} & {item['key'] for item in updated}:
        try:
            uapi = uapi_check(pins)
        except Exception as error:  # a comparison that cannot run is not a pass
            lib.log(f'GPU UAPI comparison failed: {error}')
            uapi = {'compatible': False, 'conflicts': [f'comparison failed: {str(error)[-500:]}'], 'notes': [],
                    'compared': {'constants': 0, 'structs': 0}, 'kernel_only': [], 'mesa_only': [],
                    'kernel': pins['kernel-aurora']['commit'], 'mesa': pins['mesa-aurora']['commit']}
    auto, reasons = merge_decision(items, uapi)
    packages = sorted(adapter.RECIPES[item['key']] for item in updated)
    diff = lib.git(root, 'diff', '--binary', '--src-prefix=a/', '--dst-prefix=b/')
    (output / 'changes.patch').write_text(diff + ('\n' if diff else ''))
    title = ('Track upstream: ' + ', '.join(f'{i["key"]} {i["new"][:7]}' for i in updated)) if updated else ''
    result = {'schema': 1, 'repository': args.repository, 'base': lib.git(root, 'rev-parse', 'HEAD'),
              'changes': bool(updated), 'items': items, 'uapi': uapi, 'auto_merge': auto,
              'reasons': reasons, 'ci': adapter.ci_inputs(packages), 'title': title,
              'paths': sorted(adapter.PATCH_PATHS)}
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    (output / 'summary.md').write_text(summary_markdown(args.repository, items, uapi, auto, reasons, packages))
    lib.write_github_output(changes=str(bool(updated)).lower(), auto_merge=str(auto).lower())
    print((output / 'summary.md').read_text())


def check_patch_paths(patch, allowed):
    """Refuse a planned patch that touches anything but recipe inputs."""
    files = subprocess.run(['git', 'apply', '--numstat', str(patch)], capture_output=True, text=True,
                           check=True).stdout.splitlines()
    for line in files:
        path = line.split('\t', 2)[2]
        if not any(re.fullmatch(pattern, path) for pattern in allowed):
            raise SystemExit(f'The planned patch touches {path}, which the tracker may not change.')
