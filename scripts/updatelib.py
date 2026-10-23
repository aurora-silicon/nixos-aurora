#!/usr/bin/env python3
"""Shared helpers for Aurora's automated source tracking and feed publication.

This module is copied verbatim into alarm-aurora, fedora-aurora and
nixos-aurora. Change all three copies together; `UPDATELIB_VERSION` identifies
the revision in logs and receipts.

Nothing here reads signing keys. Network access is limited to GitHub (through
the `gh` CLI or HTTPS downloads) and the source URLs recorded in sources.json.
"""
from __future__ import annotations

import base64
import email.utils
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

UPDATELIB_VERSION = 1
HEX40 = re.compile(r'[0-9a-f]{40}')
GITHUB_HOSTS = {'github.com', 'api.github.com', 'codeload.github.com', 'objects.githubusercontent.com'}
TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}


def log(message):
    print(message, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- hashes

def sha256_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sri_from_hex(hexdigest):
    """Nix SRI form of a flat SHA-256, as used by fetchurl's `hash`."""
    if not re.fullmatch(r'[0-9a-f]{64}', hexdigest):
        raise ValueError('expected a lowercase SHA-256 hex digest')
    return 'sha256-' + base64.b64encode(bytes.fromhex(hexdigest)).decode()


def hex_from_sri(sri):
    algorithm, _, value = sri.partition('-')
    if algorithm != 'sha256':
        raise ValueError('expected a sha256 SRI hash')
    raw = base64.b64decode(value, validate=True)
    if len(raw) != 32:
        raise ValueError('invalid sha256 SRI length')
    return raw.hex()


# ------------------------------------------------------------------------ downloads

def retry_delay(attempt, retry_after=None, base=5.0, cap=300.0, jitter=random.random):
    """Seconds to wait before retry `attempt` (0-based).

    A server-provided Retry-After (seconds or an HTTP date) wins, bounded by
    `cap`. Otherwise exponential backoff with up to 50% jitter.
    """
    if retry_after:
        value = str(retry_after).strip()
        if value.isdigit():
            return min(cap, float(value))
        try:
            when = email.utils.parsedate_to_datetime(value).timestamp()
            return max(1.0, min(cap, when - time.time()))
        except (TypeError, ValueError):
            pass
    delay = min(cap, base * (2 ** attempt))
    return delay * (0.5 + jitter() / 2)


def _authorized(url, token):
    host = urllib.parse.urlsplit(url).hostname or ''
    # Never send the GitHub token to a third-party mirror.
    return token and host in GITHUB_HOSTS


def download(urls, destination, *, sha256=None, attempts=8, timeout=300, token=None,
             sleep=time.sleep, opener=None, max_bytes=8 * 1024**3):
    """Fetch the first URL whose bytes match `sha256` into `destination`.

    Transient failures (HTTP 408/425/429/5xx, resets, timeouts) are retried
    with backoff that honours Retry-After. A 404 or a checksum mismatch moves
    on to the next URL. The file appears at `destination` only after it has
    been verified, so a partial or tampered download never looks complete.
    Returns the URL that produced the file.
    """
    destination = Path(destination)
    if isinstance(urls, str):
        urls = [urls]
    opener = opener or urllib.request.urlopen
    if sha256 and destination.exists() and sha256_file(destination) == sha256:
        return 'cached:' + str(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + '.partial')
    failures = []
    for url in urls:
        if urllib.parse.urlsplit(url).scheme != 'https':
            failures.append(f'{url}: refusing a non-HTTPS source')
            continue
        for attempt in range(attempts):
            headers = {'User-Agent': 'aurora-update-automation'}
            if _authorized(url, token):
                headers['Authorization'] = 'Bearer ' + token
            request = urllib.request.Request(url, headers=headers)
            retry_after = None
            try:
                with opener(request, timeout=timeout) as response, partial.open('wb') as output:
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValueError('download exceeds its size budget')
                        output.write(chunk)
            except urllib.error.HTTPError as error:
                partial.unlink(missing_ok=True)
                if error.code not in TRANSIENT_HTTP:
                    failures.append(f'{url}: HTTP {error.code}')
                    break
                retry_after = error.headers.get('Retry-After') if error.headers else None
                failures.append(f'{url}: HTTP {error.code} (attempt {attempt + 1})')
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
                partial.unlink(missing_ok=True)
                failures.append(f'{url}: {error} (attempt {attempt + 1})')
            else:
                actual = sha256_file(partial)
                if sha256 and actual != sha256:
                    partial.unlink(missing_ok=True)
                    failures.append(f'{url}: SHA-256 {actual} does not match the pinned {sha256}')
                    break
                partial.replace(destination)
                return url
            if attempt + 1 < attempts:
                delay = retry_delay(attempt, retry_after)
                log(f'Retrying {url} in {delay:.0f}s after: {failures[-1]}')
                sleep(delay)
    raise RuntimeError('No source produced the expected bytes:\n  ' + '\n  '.join(failures))


# --------------------------------------------------------------------------- GitHub

def gh(*args, attempts=5, sleep=time.sleep, check=True, input_text=None):
    """Run `gh` with retries for rate limits and transient server errors."""
    for attempt in range(attempts):
        result = subprocess.run(['gh', *args], capture_output=True, text=True, input=input_text)
        if result.returncode == 0 or not check:
            return result
        error = result.stderr
        transient = re.search(r'HTTP (429|5\d\d)|rate limit|timeout|connection reset|EOF', error, re.I)
        if not transient or attempt + 1 == attempts:
            raise RuntimeError(f'gh {" ".join(args)} failed: {error.strip()}')
        delay = retry_delay(attempt)
        log(f'gh {args[0]} {args[1] if len(args) > 1 else ""}: transient failure, retrying in {delay:.0f}s')
        sleep(delay)
    raise AssertionError('unreachable')


def gh_api(route, *fields, method=None, paginate=False):
    args = ['api']
    if method:
        args += ['--method', method]
    if paginate:
        args += ['--paginate', '--slurp']
    args.append(route)
    args += list(fields)
    output = gh(*args).stdout
    return json.loads(output) if output.strip() else None


def repository_slug(url):
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?', url)
    if not match:
        raise ValueError(f'not a GitHub repository URL: {url}')
    return match[1]


def codeload_url(slug, commit):
    if not HEX40.fullmatch(commit):
        raise ValueError('expected a full commit SHA')
    return f'https://codeload.github.com/{slug}/tar.gz/{commit}'


def branch_tip(slug, branch):
    data = gh_api(f'repos/{slug}/commits/{urllib.parse.quote(branch, safe="")}')
    sha = data['sha']
    if not HEX40.fullmatch(sha):
        raise ValueError(f'unexpected commit for {slug}@{branch}')
    return {'sha': sha, 'date': data['commit']['committer']['date'],
            'subject': data['commit']['message'].splitlines()[0]}


def compare(slug, base, head):
    """GitHub comparison status: identical, ahead, behind or diverged."""
    if base == head:
        return {'status': 'identical', 'ahead_by': 0, 'behind_by': 0, 'commits': []}
    data = gh_api(f'repos/{slug}/compare/{base}...{head}')
    return {'status': data['status'], 'ahead_by': data['ahead_by'], 'behind_by': data['behind_by'],
            'commits': [{'sha': c['sha'], 'subject': c['commit']['message'].splitlines()[0]}
                        for c in data.get('commits', [])][-50:]}


# -------------------------------------------------------------------------- archives

def _members(path):
    with tarfile.open(path, 'r:*') as archive:
        for member in archive:
            yield archive, member


def archive_root(path):
    """The single top-level directory of a source tarball."""
    roots = set()
    with tarfile.open(path, 'r:*') as archive:
        for member in archive:
            name = member.name
            if name.startswith('/') or '..' in Path(name).parts:
                raise ValueError(f'unsafe archive member: {name}')
            if member.type == tarfile.XGLTYPE or name == 'pax_global_header':
                continue
            roots.add(Path(name).parts[0])
            if len(roots) > 1:
                raise ValueError('source archive has more than one top-level entry')
    if len(roots) != 1:
        raise ValueError('source archive is empty')
    return roots.pop()


def read_members(path, wanted, limit=16 * 1024**2):
    """Return {relative path: bytes} for regular files below the archive root."""
    wanted = set(wanted)
    found = {}
    with tarfile.open(path, 'r:*') as archive:
        for member in archive:
            parts = Path(member.name).parts
            if len(parts) < 2:
                continue
            relative = '/'.join(parts[1:])
            if relative in wanted and member.isfile():
                if member.size > limit:
                    raise ValueError(f'{relative} exceeds its size budget')
                found[relative] = archive.extractfile(member).read()
                if len(found) == len(wanted):
                    break
    return found


def extract_directory(path, directory, destination, limit=64 * 1024**2):
    """Extract regular files under `directory` (relative to the archive root)."""
    destination = Path(destination)
    prefix = directory.strip('/') + '/'
    total = 0
    with tarfile.open(path, 'r:*') as archive:
        for member in archive:
            parts = Path(member.name).parts
            relative = '/'.join(parts[1:])
            if not relative.startswith(prefix) or not member.isfile():
                continue
            inner = relative[len(prefix):]
            if '..' in Path(inner).parts or inner.startswith('/'):
                raise ValueError('unsafe archive member')
            total += member.size
            if total > limit:
                raise ValueError('extracted directory exceeds its size budget')
            target = destination / inner
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
    return destination


def archive_commit_comment(path):
    """The commit ID `git archive` records in the pax global header, if any."""
    with tarfile.open(path, 'r:*') as archive:
        comment = archive.pax_headers.get('comment', '')
    return comment if HEX40.fullmatch(comment) else None


def git_tree_of_archive(path):
    """Recompute the Git tree object ID of a `git archive` tarball.

    Matching the commit's tree ID proves the archive bytes encode exactly that
    commit's content. Returns None when the archive cannot represent the tree
    (submodules or export-ignore/export-subst attributes).
    """
    import fnmatch

    def blob(data):
        return hashlib.sha1(b'blob %d\0' % len(data) + data).digest()

    root = archive_root(path)
    files = {}
    crlf_rules = []
    with tarfile.open(path, 'r:*') as archive:
        for member in archive:
            parts = Path(member.name).parts
            if member.name == 'pax_global_header' or len(parts) < 2 or parts[0] != root:
                continue
            relative = parts[1:]
            if relative == ('.gitmodules',):
                return None  # submodules are empty directories in an archive
            if member.isdir():
                continue
            if member.issym():
                files[relative] = (b'120000', blob(member.linkname.encode()), None)
                continue
            if not member.isfile():
                return None
            data = archive.extractfile(member).read()
            # Keep digests, not contents: a kernel tree is over a gigabyte.
            files[relative] = (b'100755' if member.mode & 0o111 else b'100644', blob(data),
                               blob(data.replace(b'\r\n', b'\n')) if b'\r\n' in data else None)
            if relative[-1] == '.gitattributes':
                for line in data.decode(errors='replace').splitlines():
                    fields = line.split()
                    if not fields or fields[0].startswith('#'):
                        continue
                    if any(re.match(r'-?(export-ignore|export-subst|ident|filter=|working-tree-encoding=)', f)
                           for f in fields[1:]):
                        return None
                    if 'eol=crlf' in fields[1:]:
                        crlf_rules.append((relative[:-1], fields[0]))

    def converted(relative):
        # `git archive` writes eol=crlf files with CRLF; the blob holds LF.
        for base, pattern in crlf_rules:
            if relative[:len(base)] != base:
                continue
            inner = relative[len(base):]
            target = '/'.join(inner) if '/' in pattern.strip('/') else inner[-1]
            if fnmatch.fnmatchcase(target, pattern.strip('/')):
                return True
        return False

    tree = {}
    for relative, (mode, digest, normalized) in files.items():
        if normalized is not None and crlf_rules and converted(relative):
            digest = normalized
        node = tree
        for directory in relative[:-1]:
            node = node.setdefault(directory, {})
            if not isinstance(node, dict):
                return None
        node[relative[-1]] = (mode, digest)

    def write(node):
        entries = []
        for name, value in node.items():
            if isinstance(value, dict):
                entries.append((name.encode() + b'/', b'40000', name.encode(), write(value)))
            else:
                entries.append((name.encode(), value[0], name.encode(), value[1]))
        body = b''.join(mode + b' ' + name + b'\0' + digest for _, mode, name, digest in sorted(entries))
        return hashlib.sha1(b'tree %d\0' % len(body) + body).digest()

    return write(tree).hex()


def commit_tree(slug, commit):
    return gh_api(f'repos/{slug}/git/commits/{commit}')['tree']['sha']


def kernel_version(makefile):
    """`VERSION.PATCHLEVEL.SUBLEVEL` plus EXTRAVERSION from a kernel Makefile."""
    fields = {}
    for line in makefile.splitlines()[:20]:
        match = re.fullmatch(r'(VERSION|PATCHLEVEL|SUBLEVEL|EXTRAVERSION)\s*=\s*(\S*)\s*', line)
        if match:
            fields[match[1]] = match[2]
    if not all(fields.get(name, '').isdigit() for name in ('VERSION', 'PATCHLEVEL', 'SUBLEVEL')):
        raise ValueError('kernel Makefile has no numeric version')
    return '{VERSION}.{PATCHLEVEL}.{SUBLEVEL}'.format(**fields) + fields.get('EXTRAVERSION', '')


def mesa_version(text):
    value = text.strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(-[A-Za-z0-9]+)?', value):
        raise ValueError(f'unexpected Mesa VERSION: {value!r}')
    return value


# --------------------------------------------------------------- version comparison

def _isalpha(c):
    return ('a' <= c <= 'z') or ('A' <= c <= 'Z')


def _isdigit(c):
    return '0' <= c <= '9'


def _isalnum(c):
    return _isalpha(c) or _isdigit(c)


def _segment(text, start):
    end = start
    numeric = _isdigit(text[start])
    test = _isdigit if numeric else _isalpha
    while end < len(text) and test(text[end]):
        end += 1
    return text[start:end], end, numeric


def _compare_segments(one, two, numeric):
    if numeric:
        one, two = one.lstrip('0'), two.lstrip('0')
        if len(one) != len(two):
            return 1 if len(one) > len(two) else -1
    if one != two:
        return 1 if one > two else -1
    return 0


def rpmvercmp(a, b):
    """RPM's version segment comparison, including ~ (sorts first) and ^."""
    if a == b:
        return 0
    i = j = 0
    while i < len(a) or j < len(b):
        while i < len(a) and not _isalnum(a[i]) and a[i] not in '~^':
            i += 1
        while j < len(b) and not _isalnum(b[j]) and b[j] not in '~^':
            j += 1
        if (i < len(a) and a[i] == '~') or (j < len(b) and b[j] == '~'):
            if i >= len(a) or a[i] != '~':
                return 1
            if j >= len(b) or b[j] != '~':
                return -1
            i, j = i + 1, j + 1
            continue
        if (i < len(a) and a[i] == '^') or (j < len(b) and b[j] == '^'):
            if i >= len(a):
                return -1
            if j >= len(b):
                return 1
            if a[i] != '^':
                return 1
            if b[j] != '^':
                return -1
            i, j = i + 1, j + 1
            continue
        if not (i < len(a) and j < len(b)):
            break
        one, i_end, numeric = _segment(a, i)
        if numeric:
            k = j
            while k < len(b) and _isdigit(b[k]):
                k += 1
        else:
            k = j
            while k < len(b) and _isalpha(b[k]):
                k += 1
        two = b[j:k]
        if not two:
            return 1 if numeric else -1
        result = _compare_segments(one, two, numeric)
        if result:
            return result
        i, j = i_end, k
    if i >= len(a) and j >= len(b):
        return 0
    return -1 if i >= len(a) else 1


def _alpm_rpmvercmp(a, b):
    """libalpm's rpmvercmp: separator lengths matter and no ~/^ rules."""
    if a == b:
        return 0
    i = j = 0
    while i < len(a) and j < len(b):
        si, sj = i, j
        while i < len(a) and not _isalnum(a[i]):
            i += 1
        while j < len(b) and not _isalnum(b[j]):
            j += 1
        if not (i < len(a) and j < len(b)):
            break
        if (i - si) != (j - sj):
            return -1 if (i - si) < (j - sj) else 1
        one, i_end, numeric = _segment(a, i)
        k = j
        test = _isdigit if numeric else _isalpha
        while k < len(b) and test(b[k]):
            k += 1
        two = b[j:k]
        if not two:
            return 1 if numeric else -1
        result = _compare_segments(one, two, numeric)
        if result:
            return result
        i, j = i_end, k
    if i >= len(a) and j >= len(b):
        return 0
    rest_a = a[i:]
    rest_b = b[j:]
    if (not rest_a and not (rest_b and _isalpha(rest_b[0]))) or (rest_a and _isalpha(rest_a[0])):
        return -1
    return 1


def _alpm_parse(version):
    # libalpm's parseEVR: an epoch is leading digits followed by ':'.
    digits = len(version) - len(version.lstrip('0123456789'))
    if version[digits:digits + 1] == ':':
        epoch, rest = version[:digits] or '0', version[digits + 1:]
    else:
        epoch, rest = '0', version
    ver, sep, rel = rest.rpartition('-')
    if not sep:
        ver, rel = rest, ''
    return epoch, ver, rel


def alpm_vercmp(a, b):
    """pacman's `vercmp` for full `[epoch:]pkgver[-pkgrel]` strings."""
    if a == b:
        return 0
    e1, v1, r1 = _alpm_parse(a)
    e2, v2, r2 = _alpm_parse(b)
    result = _alpm_rpmvercmp(e1, e2)
    if result == 0:
        result = _alpm_rpmvercmp(v1, v2)
        if result == 0 and r1 and r2:
            result = _alpm_rpmvercmp(r1, r2)
    return result


def rpm_evr_compare(left, right):
    """Compare (epoch, version, release) tuples the way rpm/dnf do."""
    e1, v1, r1 = left
    e2, v2, r2 = right
    e1, e2 = int(e1 or 0), int(e2 or 0)
    if e1 != e2:
        return 1 if e1 > e2 else -1
    return rpmvercmp(v1, v2) or rpmvercmp(r1 or '', r2 or '')


def regressions(old, new, compare):
    """Names whose version in `new` sorts before the one in `old`.

    `old` and `new` map a package identity to a version. Returns
    (downgraded, removed, added) for reporting.
    """
    downgraded = sorted((name, old[name], new[name]) for name in old.keys() & new.keys()
                        if compare(new[name], old[name]) < 0)
    return downgraded, sorted(old.keys() - new.keys()), sorted(new.keys() - old.keys())


# --------------------------------------------------------------------- GPU UAPI ABI

_UNNAMED = re.compile(r'\(unnamed at [^)]*\)')


def _uapi_symbols(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    text = re.sub(r'//[^\n]*', '', text)
    macros = set(re.findall(r'^\s*#\s*define\s+([A-Za-z_]\w*)\s+\S', text, re.M))
    macros -= set(re.findall(r'^\s*#\s*define\s+([A-Za-z_]\w*)\(', text, re.M))
    macros = {name for name in macros if not name.startswith('_')}
    enumerators = set()
    for body in re.findall(r'\benum\s+\w*\s*\{(.*?)\}', text, re.S):
        for part in body.split(','):
            match = re.match(r'\s*([A-Za-z_]\w*)\s*(?:=|$)', part)
            if match:
                enumerators.add(match[1])
    structs = set(re.findall(r'\bstruct\s+([A-Za-z_]\w*)\s*\{', text))
    return macros, enumerators, structs


def _compile_values(directory, header, names, cc):
    """Evaluate integer constant expressions with the host compiler."""
    if not names:
        return {}
    with tempfile.TemporaryDirectory(prefix='aurora-uapi-') as temporary:
        source = Path(temporary) / 'probe.c'
        binary = Path(temporary) / 'probe'
        body = ''.join(f'  printf("%s %lld\\n", "{name}", (long long)({name}));\n' for name in sorted(names))
        source.write_text(f'#include <stdio.h>\n#include "{header}"\nint main(void) {{\n{body}  return 0;\n}}\n')
        result = subprocess.run([cc, '-w', '-D__user=', '-I', str(directory), '-o', str(binary), str(source)],
                                capture_output=True, text=True)
        if result.returncode:
            if len(names) == 1:
                return {next(iter(names)): None}
            # Some macros are not integer constants; probe them one by one.
            values = {}
            for name in names:
                values.update(_compile_values(directory, header, {name}, cc))
            return values
        output = subprocess.check_output([str(binary)], text=True)
    return {name: int(value) for name, value in (line.split(' ', 1) for line in output.splitlines())}


def _record_layouts(directory, header, structs, cc):
    if not structs:
        return {}
    with tempfile.TemporaryDirectory(prefix='aurora-uapi-') as temporary:
        source = Path(temporary) / 'layout.c'
        probes = ''.join(f'char aurora_probe_{index}[sizeof(struct {name})];\n'
                         for index, name in enumerate(sorted(structs)))
        source.write_text(f'#include "{header}"\n{probes}')
        output = subprocess.run([cc, '-fsyntax-only', '-w', '-D__user=', '-Xclang', '-fdump-record-layouts',
                                 '-I', str(directory), str(source)], capture_output=True, text=True, check=True).stdout
    layouts = {}
    for block in output.split('*** Dumping AST Record Layout')[1:]:
        lines = [line.rstrip() for line in block.strip().splitlines() if line.strip()]
        if not lines:
            continue
        match = re.fullmatch(r'\s*0 \| struct (\S+)', _UNNAMED.sub('(unnamed)', lines[0]))
        if not match or match[1] not in structs:
            continue
        fields = []
        size = None
        for line in lines[1:]:
            offset, _, rest = line.partition('|')
            rest = _UNNAMED.sub('(unnamed)', rest)
            summary = re.fullmatch(r'\s*\[sizeof=(\d+), align=(\d+)', rest.split(']')[0])
            if summary:
                size = (int(summary[1]), int(summary[2]))
                continue
            depth = (len(rest) - len(rest.lstrip(' '))) // 2
            words = rest.strip().rsplit(' ', 1)
            fields.append({'offset': offset.strip(), 'depth': depth, 'type': words[0] if len(words) == 2 else '',
                           'name': words[-1]})
        layouts[match[1]] = {'size': size, 'fields': fields}
    return layouts


def uapi_report(kernel_dir, mesa_dir, header='asahi_drm.h', cc=None):
    """Compare the GPU UAPI as the kernel defines it and as Mesa uses it.

    Only definitions present on both sides can conflict: a different value,
    record size, alignment or field offset is an ABI break. A field renamed at
    the same offset is reported as a note. Definitions only one side has are
    listed for review; Mesa may carry probed-for future interfaces.
    """
    cc = cc or shutil.which('clang') or shutil.which('cc')
    if not cc:
        raise RuntimeError('a C compiler is required for the UAPI comparison')
    kernel_dir, mesa_dir = Path(kernel_dir), Path(mesa_dir)
    k_macros, k_enums, k_structs = _uapi_symbols((kernel_dir / header).read_text())
    m_macros, m_enums, m_structs = _uapi_symbols((mesa_dir / header).read_text())
    constants = (k_macros | k_enums) & (m_macros | m_enums)
    structs = k_structs & m_structs
    k_values = _compile_values(kernel_dir, header, constants, cc)
    m_values = _compile_values(mesa_dir, header, constants, cc)
    conflicts, notes = [], []
    for name in sorted(constants):
        if k_values.get(name) != m_values.get(name):
            conflicts.append(f'{name}: kernel {k_values.get(name)} != Mesa {m_values.get(name)}')
    k_layout = _record_layouts(kernel_dir, header, structs, cc)
    m_layout = _record_layouts(mesa_dir, header, structs, cc)
    for name in sorted(structs):
        left, right = k_layout.get(name), m_layout.get(name)
        if not left or not right:
            conflicts.append(f'struct {name}: layout unavailable')
            continue
        k_fields = [(f['offset'], f['depth'], f['type']) for f in left['fields']]
        m_fields = [(f['offset'], f['depth'], f['type']) for f in right['fields']]
        common = min(len(k_fields), len(m_fields))
        if k_fields[:common] != m_fields[:common]:
            index = next(i for i in range(common) if k_fields[i] != m_fields[i])
            conflicts.append(f'struct {name}: kernel field {left["fields"][index]} != Mesa {right["fields"][index]}')
            continue
        if left['size'] != right['size']:
            # Size-versioned commands may grow at the end (drm_asahi_cmd_header
            # carries the size). The shorter layout must be an exact prefix and
            # must end before the first appended field.
            shorter, longer = (left, right) if left['size'][0] < right['size'][0] else (right, left)
            extra = longer['fields'][common:]
            first = int(re.match(r'\d+', extra[0]['offset'])[0]) if extra else None
            if left['size'][1] != right['size'][1] or first is None or shorter['size'][0] > first:
                conflicts.append(f'struct {name}: kernel size/align {left["size"]} != Mesa {right["size"]}')
                continue
            side = 'kernel' if longer is left else 'Mesa'
            notes.append(f'struct {name}: {side} appends {len(extra)} field(s) after byte {first} '
                         f'(kernel {left["size"][0]} bytes, Mesa {right["size"][0]} bytes)')
        elif len(k_fields) != len(m_fields):
            notes.append(f'struct {name}: same size, kernel {len(k_fields)} / Mesa {len(m_fields)} fields')
        for a, b in zip(left['fields'], right['fields']):
            if a['name'] != b['name']:
                notes.append(f'struct {name} @{a["offset"]}: kernel {a["name"]} / Mesa {b["name"]}')
    return {
        'compatible': not conflicts,
        'conflicts': conflicts,
        'notes': notes,
        'compared': {'constants': len(constants), 'structs': len(structs)},
        'kernel_only': sorted(((k_macros | k_enums) - (m_macros | m_enums)) | {f'struct {s}' for s in k_structs - m_structs}),
        'mesa_only': sorted(((m_macros | m_enums) - (k_macros | k_enums)) | {f'struct {s}' for s in m_structs - k_structs}),
    }


# ----------------------------------------------------------------------- git helpers

def git(root, *args, check=True):
    return subprocess.run(['git', '-C', str(root), *args], check=check, capture_output=True, text=True).stdout.strip()


def is_ancestor(root, commit, head='HEAD'):
    return subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', commit, head],
                          capture_output=True).returncode == 0


def tree_id(root, commit, path):
    """Object ID of `path` at `commit`, or None when it does not exist."""
    result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', '--quiet', f'{commit}:{path}'],
                            capture_output=True, text=True)
    return result.stdout.strip() or None


def json_at(root, commit, path):
    return json.loads(git(root, 'show', f'{commit}:{path}'))


# -------------------------------------------------------------------- channel state

CHANNELS_BRANCH = 'channels'
CHANNELS_FILE = 'channels.json'


def empty_channels(repository):
    return {'schema': 1, 'repository': repository, 'channels': {}, 'history': []}


def load_channels(root, repository, remote='origin'):
    """Read the channel pointer file from the `channels` branch, if any."""
    fetched = subprocess.run(['git', '-C', str(root), 'fetch', '--quiet', remote,
                              f'+refs/heads/{CHANNELS_BRANCH}:refs/remotes/{remote}/{CHANNELS_BRANCH}'],
                             capture_output=True, text=True)
    if fetched.returncode:
        if "couldn't find remote ref" in fetched.stderr or 'not found' in fetched.stderr:
            return empty_channels(repository)
        raise RuntimeError('could not fetch the channel state: ' + fetched.stderr.strip())
    data = json.loads(git(root, 'show', f'{remote}/{CHANNELS_BRANCH}:{CHANNELS_FILE}'))
    if data.get('schema') != 1 or data.get('repository') != repository:
        raise ValueError('channel state belongs to another repository or schema')
    return data


def record_channel(state, channel, entry, keep=200):
    if channel not in ('testing', 'stable'):
        raise ValueError('unknown channel')
    state = json.loads(json.dumps(state))
    state['channels'][channel] = entry
    state['history'] = ([{'channel': channel, **entry}] + state.get('history', []))[:keep]
    return state


def served_on(state, channel, key, value):
    """History entries for `channel` whose `key` equals `value`, newest first."""
    return [item for item in state.get('history', []) if item.get('channel') == channel and item.get(key) == value]


def write_github_output(**values):
    path = os.environ.get('GITHUB_OUTPUT')
    lines = []
    for key, value in values.items():
        if not isinstance(value, str):
            value = json.dumps(value, separators=(',', ':'))
        if '\n' in value:
            raise ValueError('multi-line outputs are not supported')
        lines.append(f'{key}={value}\n')
    if path:
        with open(path, 'a') as output:
            output.writelines(lines)
    else:
        sys.stdout.writelines(lines)


def next_snapshot_tag(existing, prefix, today):
    """`<prefix>YYYYMMDD.N` with N one above the highest existing for today."""
    stem = f'{prefix}{today}.'
    numbers = [int(tag[len(stem):]) for tag in existing if tag.startswith(stem) and tag[len(stem):].isdigit()]
    return f'{stem}{max(numbers, default=0) + 1}'


def commit_channels(root, state, message, remote='origin'):
    """Commit channels.json to the `channels` branch and push it.

    The branch holds only channel state: which immutable snapshot each channel
    serves and when it changed. Workflows are its only writers.
    """
    root = Path(root)
    bot = ['-c', 'user.name=github-actions[bot]',
           '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com']
    with tempfile.TemporaryDirectory(prefix='aurora-channels-') as temporary:
        work = Path(temporary) / 'channels'
        exists = subprocess.run(['git', '-C', str(root), 'fetch', '--quiet', remote,
                                 f'+refs/heads/{CHANNELS_BRANCH}:refs/remotes/{remote}/{CHANNELS_BRANCH}'],
                                capture_output=True).returncode == 0
        if exists:
            git(root, 'worktree', 'add', '--quiet', '--detach', str(work), f'refs/remotes/{remote}/{CHANNELS_BRANCH}')
        else:
            git(root, 'worktree', 'add', '--quiet', '--detach', str(work))
            git(work, 'checkout', '--quiet', '--orphan', CHANNELS_BRANCH)
            git(work, 'rm', '-rf', '--quiet', '.')
        try:
            (work / CHANNELS_FILE).write_text(json.dumps(state, indent=2, sort_keys=True) + '\n')
            (work / 'README.md').write_text(
                '# Channel state\n\nWritten by the deploy and promotion workflows. `channels.json` names the '
                'immutable signed snapshot each update channel serves and keeps a history of changes. '
                'Do not edit by hand; dispatch the workflows instead.\n')
            git(work, 'add', CHANNELS_FILE, 'README.md')
            if subprocess.run(['git', '-C', str(work), 'diff', '--cached', '--quiet']).returncode:
                git(work, *bot, 'commit', '--quiet', '-m', message)
                git(work, 'push', '--quiet', remote, f'HEAD:refs/heads/{CHANNELS_BRANCH}')
        finally:
            git(root, 'worktree', 'remove', '--force', str(work), check=False)
