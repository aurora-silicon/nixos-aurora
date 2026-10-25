"""Tests for scripts/updatelib.py and scripts/trackerlib.py (shared verbatim by
alarm-aurora, fedora-aurora and nixos-aurora)."""
import datetime
import email.message
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib.error

sys.dont_write_bytecode = True  # scripts/ is scanned with bash -n in CI
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import trackerlib as tl  # noqa: E402
import updatelib as lib  # noqa: E402

A = 'a' * 40
B = 'b' * 40


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def http_error(code, retry_after=None):
    headers = email.message.Message()
    if retry_after is not None:
        headers['Retry-After'] = retry_after
    return urllib.error.HTTPError('https://example.invalid', code, 'error', headers, None)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name) / 'source.tar.gz'
        self.data = b'archive bytes'
        self.digest = hashlib.sha256(self.data).hexdigest()
        self.sleeps = []

    def fetch(self, responses, urls=('https://codeload.github.com/o/r/tar.gz/' + A,), **kwargs):
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, dict(request.header_items())))
            outcome = responses.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return Response(outcome)

        used = lib.download(list(urls), self.target, sha256=self.digest, opener=opener,
                            sleep=self.sleeps.append, **kwargs)
        return used, calls

    def test_rate_limits_are_retried_honouring_retry_after(self):
        used, calls = self.fetch([http_error(429, '7'), http_error(503), self.data])
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.sleeps[0], 7.0)
        self.assertEqual(self.target.read_bytes(), self.data)
        self.assertTrue(used.startswith('https://codeload.github.com/'))

    def test_checksum_mismatch_moves_to_the_next_source_and_never_lands(self):
        urls = ('https://github.com/o/r/releases/download/source-cache/x.tar.gz',
                'https://codeload.github.com/o/r/tar.gz/' + A)
        used, _ = self.fetch([b'tampered', self.data], urls=urls)
        self.assertEqual(used, urls[1])
        with self.assertRaisesRegex(RuntimeError, 'does not match'):
            self.target.unlink()
            self.fetch([b'tampered'], urls=urls[:1])
        self.assertFalse(self.target.exists())
        self.assertFalse(self.target.with_name(self.target.name + '.partial').exists())

    def test_missing_mirror_falls_through_and_plain_http_is_refused(self):
        used, _ = self.fetch([http_error(404), self.data],
                             urls=('http://insecure.invalid/x', 'https://github.com/o/r/releases/download/t/x',
                                   'https://codeload.github.com/o/r/tar.gz/' + A))
        self.assertEqual(used, 'https://codeload.github.com/o/r/tar.gz/' + A)

    def test_github_token_is_sent_only_to_github(self):
        _, calls = self.fetch([http_error(404), self.data], token='secret',
                              urls=('https://mirror.example.org/x', 'https://codeload.github.com/o/r/tar.gz/' + A))
        self.assertNotIn('Authorization', calls[0][1])
        self.assertEqual(calls[1][1]['Authorization'], 'Bearer secret')

    def test_verified_existing_file_is_reused(self):
        self.target.write_bytes(self.data)
        used, calls = self.fetch([])
        self.assertTrue(used.startswith('cached:'))
        self.assertEqual(calls, [])

    def test_retry_delay_is_bounded(self):
        self.assertEqual(lib.retry_delay(0, '9999'), 300.0)
        self.assertLessEqual(lib.retry_delay(20, jitter=lambda: 1.0), 300.0)
        self.assertEqual(lib.retry_delay(1, jitter=lambda: 1.0), 10.0)


class HashAndArchiveTests(unittest.TestCase):
    def test_sri_round_trip(self):
        digest = 'a28ff3dc334fed46089997af76dd6cfdb4ef443da956d3c646ac011ffad9a634'
        self.assertEqual(lib.sri_from_hex(digest), 'sha256-oo/z3DNP7UYImZevdt1s/bTvRD2pVtPGRqwBH/rZpjQ=')
        self.assertEqual(lib.hex_from_sri(lib.sri_from_hex(digest)), digest)
        with self.assertRaises(ValueError):
            lib.sri_from_hex('ABC')

    def test_versions(self):
        makefile = 'SPDX\nVERSION = 7\nPATCHLEVEL = 3\nSUBLEVEL = 0\nEXTRAVERSION = -rc2\nNAME = x\n'
        self.assertEqual(lib.kernel_version(makefile), '7.3.0-rc2')
        self.assertEqual(lib.mesa_version('26.3.0-devel\n'), '26.3.0-devel')
        self.assertEqual(tl.rpm_version('7.4.0-rc1'), '7.4.0~rc1')
        self.assertEqual(tl.rpm_version('26.3.0-devel'), '26.3.0')
        self.assertEqual(tl.pacman_version('7.4.0-rc1'), '7.4.0rc1')

    @unittest.skipUnless(shutil.which('git'), 'git is required')
    def test_archive_tree_matches_git_including_crlf_attributes(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / 'repo'
            (repo / 'sub').mkdir(parents=True)
            (repo / 'README').write_text('hello\n')
            (repo / 'run.sh').write_text('#!/bin/sh\n')
            (repo / 'run.sh').chmod(0o755)
            (repo / 'sub' / 'table.csv').write_text('a,b\n1,2\n')
            (repo / '.gitattributes').write_text('* text=auto\n*.csv eol=crlf\n')
            (repo / 'link').symlink_to('README')
            git = ['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.org']
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            subprocess.run(git + ['add', '.'], check=True)
            subprocess.run(git + ['commit', '-qm', 'fixture'], check=True)
            archive = Path(temporary) / 'repo.tar.gz'
            subprocess.run(git + ['archive', '--format=tar.gz', '--prefix=repo-x/', '-o', str(archive), 'HEAD'],
                           check=True)
            tree = subprocess.check_output(git + ['rev-parse', 'HEAD^{tree}'], text=True).strip()
            commit = subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()
            self.assertIn(b'\r\n', subprocess.check_output(['tar', '-xzOf', str(archive), 'repo-x/sub/table.csv']))
            self.assertEqual(lib.git_tree_of_archive(archive), tree)
            self.assertEqual(lib.archive_root(archive), 'repo-x')
            self.assertEqual(lib.archive_commit_comment(archive), commit)
            self.assertEqual(lib.read_members(archive, ['README']), {'README': b'hello\n'})
            (repo / '.gitattributes').write_text('* text=auto\nsecret export-ignore\n')
            subprocess.run(git + ['commit', '-qam', 'ignore'], check=True)
            subprocess.run(git + ['archive', '--format=tar.gz', '--prefix=repo-x/', '-o', str(archive), 'HEAD'],
                           check=True)
            self.assertIsNone(lib.git_tree_of_archive(archive))

    def test_unsafe_or_multi_root_archives_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'bad.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                for name in ('one/a', 'two/b'):
                    info = tarfile.TarInfo(name)
                    tar.addfile(info, io.BytesIO(b''))
            with self.assertRaisesRegex(ValueError, 'more than one'):
                lib.archive_root(archive)


class VersionComparisonTests(unittest.TestCase):
    def test_pacman_semantics(self):
        cases = [('1.0', '1.0.1', -1), ('1.0a', '1.0', -1), ('1:0.9', '2.0', 1), ('1.0-2', '1.0-10', -1),
                 ('7.3.0rc1.aurora1-1', '7.3.0.aurora1-1', -1), ('7.2.10.aurora1-6', '7.3.0.aurora1-1', -1),
                 ('1:26.3.0_devel.20261020.2305fd923ca-1', '1:26.3.0_devel.20261023.a7e83fc2bc2-1', -1),
                 ('0.1.0.r20261022-3', '0.1.0.r20261022-4', -1), ('1.0', '1.0-5', 0)]
        for a, b, expected in cases:
            with self.subTest(a=a, b=b):
                self.assertEqual(lib.alpm_vercmp(a, b), expected)
                self.assertEqual(lib.alpm_vercmp(b, a), -expected)

    @unittest.skipUnless(shutil.which('vercmp'), 'pacman vercmp is not installed')
    def test_matches_pacman_vercmp(self):
        values = ['1.0', '1.0.1', '1.0a', '1.0.a', '1_0', '1:0.9', '1.0-1', '1.0-2', '1..0', '1.0rc1', '10', 'a']
        for a in values:
            for b in values:
                expected = int(subprocess.check_output(['vercmp', a, b], text=True))
                self.assertEqual(lib.alpm_vercmp(a, b), (expected > 0) - (expected < 0), (a, b))

    def test_rpm_semantics(self):
        cases = [('1.0~rc1', '1.0', -1), ('1.0^git1', '1.0', 1), ('1.0^git1', '1.01', -1), ('6.0.rc1', '6.0', 1),
                 ('10.0001', '10.1', 0), ('2.0', '2_0', 0), ('5.5p10', '5.5p1', 1), ('1.0~rc1^git1', '1.0~rc1', 1)]
        for a, b, expected in cases:
            with self.subTest(a=a, b=b):
                self.assertEqual(lib.rpmvercmp(a, b), expected)
        self.assertEqual(lib.rpm_evr_compare(('1', '1.0', '1'), ('0', '9.0', '1')), 1)
        self.assertEqual(lib.rpm_evr_compare(('0', '7.3.0', '1.fc44.aurora'), ('', '7.2.10', '7.fc44.aurora')), 1)

    def test_regressions(self):
        downgraded, removed, added = lib.regressions({'a': '2', 'b': '1', 'c': '1'}, {'a': '1', 'b': '2', 'd': '1'},
                                                    lib.alpm_vercmp)
        self.assertEqual(downgraded, [('a', '2', '1')])
        self.assertEqual((removed, added), (['c'], ['d']))

    def test_snapshot_tags(self):
        existing = ['testing-20261023.1', 'testing-20261023.2', 'testing-20261022.9', 'cache-testing-20261023.4']
        self.assertEqual(lib.next_snapshot_tag(existing, 'testing-', '20261023'), 'testing-20261023.3')
        self.assertEqual(lib.next_snapshot_tag(existing, 'cache-testing-', '20261023'), 'cache-testing-20261023.5')
        self.assertEqual(lib.next_snapshot_tag(existing, 'testing-', '20261024'), 'testing-20261024.1')


@unittest.skipUnless(shutil.which('clang'), 'clang is required for the UAPI comparison')
class UapiTests(unittest.TestCase):
    HEADER = '''#include "drm.h"
#define DRM_ASAHI_GET_PARAMS 0x00
#define DRM_ASAHI_MAX {max}
enum drm_asahi_kind {{ DRM_ASAHI_KIND_A = 1, DRM_ASAHI_KIND_B = {kind_b}, }};
struct drm_asahi_cmd {{ __u32 flags; __u32 {name}; __u64 base;{extra} }};
struct drm_asahi_get_params {{ __u32 param_group; __u32 pad; __u64 pointer; __u64 size; }};
#define DRM_IOCTL_ASAHI_GET_PARAMS DRM_IOWR(DRM_COMMAND_BASE + DRM_ASAHI_GET_PARAMS, struct drm_asahi_get_params)
'''

    def write(self, directory, **values):
        directory.mkdir()
        (directory / 'drm.h').write_text('#include <linux/types.h>\n#include <asm/ioctl.h>\n'
                                         '#define DRM_COMMAND_BASE 0x40\n#define DRM_IOWR(nr,type) _IOWR(\'d\', nr, type)\n')
        params = {'max': 64, 'kind_b': 2, 'name': 'count', 'extra': ''}
        params.update(values)
        (directory / 'asahi_drm.h').write_text(self.HEADER.format(**params))
        return directory

    def report(self, kernel, mesa):
        with tempfile.TemporaryDirectory() as temporary:
            k = self.write(Path(temporary) / 'k', **kernel)
            m = self.write(Path(temporary) / 'm', **mesa)
            return lib.uapi_report(k, m)

    def test_identical_and_extended_layouts_are_compatible(self):
        self.assertTrue(self.report({}, {})['compatible'])
        extended = self.report({'extra': ' __u64 added;'}, {})
        self.assertTrue(extended['compatible'])
        self.assertTrue(any('appends 1 field' in note for note in extended['notes']))
        renamed = self.report({'name': 'flags2'}, {})
        self.assertTrue(renamed['compatible'] and renamed['notes'])

    def test_value_and_layout_changes_conflict(self):
        self.assertFalse(self.report({'max': 32}, {})['compatible'])
        self.assertFalse(self.report({'kind_b': 3}, {})['compatible'])
        moved = self.report({'name': 'count; __u32 inserted'}, {})
        self.assertFalse(moved['compatible'])


class TrackerTests(unittest.TestCase):
    def tracking(self):
        return {'schema': 1, 'branch': 'auto/track-sources', 'sources': {
            'aura': {'repository': 'aurora-silicon/aura', 'branch': 'main', 'merge': 'auto'},
            'kernel-aurora': {'repository': 'aurora-silicon/linux', 'branch': 'integration/aurora',
                              'merge': 'auto-same-version'},
            'mesa-aurora': {'repository': 'aurora-silicon/mesa', 'branch': 'aurora-wip', 'merge': 'manual'}}}

    def test_plan_classifies_every_source(self):
        pins = {'aura': {'repository': 'https://github.com/aurora-silicon/aura', 'commit': A},
                'kernel-aurora': {'repository': 'https://github.com/omacom/linux-aurora', 'commit': A},
                'mesa-aurora': {'repository': 'https://github.com/aurora-silicon/mesa', 'commit': A}}
        tips = {'aurora-silicon/aura': A, 'aurora-silicon/mesa': B}
        resolve = lambda slug, branch: {'sha': tips[slug], 'date': '2026-10-23T00:00:00Z', 'subject': 's'}
        compare = lambda slug, base, head, branch: {'status': 'diverged', 'commits': []}
        items = {item['key']: item for item in tl.plan(Path('.'), self.tracking(), pins, resolve, compare)}
        self.assertEqual(items['aura']['status'], 'current')
        self.assertEqual(items['kernel-aurora']['status'], 'repository-switch-required')
        self.assertEqual(items['mesa-aurora']['status'], 'update')
        self.assertTrue(items['mesa-aurora']['rewritten'])
        compare_behind = lambda slug, base, head, branch: {'status': 'behind', 'commits': []}
        items = {item['key']: item for item in tl.plan(Path('.'), self.tracking(), pins, resolve, compare_behind)}
        self.assertEqual(items['mesa-aurora']['status'], 'pin-ahead-of-branch')

    def test_merge_policy(self):
        base = {'status': 'update', 'tree_verified': True}
        auto, reasons = tl.merge_decision([{**base, 'key': 'aura', 'merge': 'auto'}], None)
        self.assertTrue(auto)
        cases = [{**base, 'key': 'mesa', 'merge': 'manual'},
                 {**base, 'key': 'kernel', 'merge': 'auto-same-version', 'version_changed': True, 'version': '7.4.0'},
                 {**base, 'key': 'aura', 'merge': 'auto', 'rewritten': True},
                 {**base, 'key': 'aura', 'merge': 'auto', 'tree_verified': False}]
        for item in cases:
            with self.subTest(item=item):
                self.assertFalse(tl.merge_decision([item], None)[0])
        self.assertFalse(tl.merge_decision([{**base, 'key': 'aura', 'merge': 'auto'}],
                                           {'compatible': False})[0])

    def test_commit_replacement_covers_abbreviations_only_of_the_old_commit(self):
        text = f'_commit={A}\npkgver=26.3.0.{A[:11]}\nother={B[:11]}\n'
        updated = tl.replace_commit(text, A, B)
        self.assertEqual(updated, f'_commit={B}\npkgver=26.3.0.{B[:11]}\nother={B[:11]}\n')
        with self.assertRaises(ValueError):
            tl.replace_commit(text, 'short', B)

    def test_spec_release_and_changelog(self):
        spec = 'Version: 0.1.0\nRelease: 4%{?dist}\n\n%changelog\n* Old - 0.1.0-4\n- old\n'
        spec, number = tl.bump_spec_release(spec, reset=False)
        self.assertEqual(number, 5)
        self.assertIn('Release: 5%{?dist}\n', spec)
        spec = tl.add_spec_changelog(spec, '0.1.0', 5, ['Track aura main at abcdef0.'],
                                     datetime.date(2026, 10, 23))
        self.assertIn('%changelog\n* Fri Oct 23 2026 Aurora Silicon <hey@djdev.me> - 0.1.0-5\n'
                      '- Track aura main at abcdef0.\n\n* Old', spec)
        self.assertIn('Release: 1%{?dist}', tl.bump_spec_release(spec, reset=True)[0])

    def test_pr_record_round_trip(self):
        record = {'head': A, 'targets': {'aura': B}, 'auto_merge': True}
        body = f'summary\n<!-- {tl.MARKER} {json.dumps(record)} -->\n'
        self.assertEqual(tl.pr_record({'body': body}), record)
        self.assertIsNone(tl.pr_record({'body': 'no marker'}))

    def test_pin_edits_keep_the_file_layout(self):
        text = ('{\n  "aura": {\n    "commit": "%s",\n    "sha256": "x"\n  },\n'
                '  "odd": {\n      "commit": "%s"\n  }\n}\n') % (A, A)
        pins = json.loads(text)
        pins['aura'] = {'commit': B, 'sha256': 'y', 'nix_hash': 'sha256-z'}
        updated = tl.edit_pins_text(text, pins)
        self.assertEqual(json.loads(updated), pins)
        self.assertIn('      "commit": "%s"' % A, updated)
        self.assertIn('    "nix_hash": "sha256-z"\n  },', updated)
        with self.assertRaises(ValueError):
            tl.edit_pins_text(text, {**pins, 'new': {}})

    def test_channel_records(self):
        state = lib.empty_channels('aurora-silicon/x')
        state = lib.record_channel(state, 'testing', {'tag': 'testing-1'})
        state = lib.record_channel(state, 'stable', {'tag': 'testing-1'})
        self.assertEqual(state['channels']['stable']['tag'], 'testing-1')
        self.assertEqual(len(lib.served_on(state, 'testing', 'tag', 'testing-1')), 1)
        with self.assertRaises(ValueError):
            lib.record_channel(state, 'beta', {})



class CompareTests(unittest.TestCase):
    DIFF_ERROR = ('gh api repos/o/r/compare failed: gh: Server Error: Sorry, this diff is '
                  'temporarily unavailable due to heavy server load. (HTTP 500)')

    def runner(self, rest=None, graphql=None):
        calls = []

        def run(*args):
            calls.append(args)
            if args[1] == 'graphql':
                return subprocess.CompletedProcess(args, 0, json.dumps(graphql), '')
            if isinstance(rest, Exception):
                raise rest
            return subprocess.CompletedProcess(args, 0, json.dumps(rest), '')
        return run, calls

    @staticmethod
    def branch(target, status, ahead_by, behind_by, history=()):
        nodes = [{'oid': oid, 'messageHeadline': f'commit {oid[0]}'} for oid in history]
        return {'data': {'repository': {'ref': {
            'target': {'oid': target, 'history': {'nodes': nodes}},
            'compare': {'status': status, 'aheadBy': ahead_by, 'behindBy': behind_by}}}}}

    def test_rest_comparison_is_used_when_it_answers(self):
        rest = {'status': 'ahead', 'ahead_by': 1, 'behind_by': 0,
                'commits': [{'sha': B, 'commit': {'message': 'subject\nbody'}}]}
        run, calls = self.runner(rest)
        self.assertEqual(lib.compare('o/r', A, B, branch='main', run=run),
                         {'status': 'ahead', 'ahead_by': 1, 'behind_by': 0,
                          'commits': [{'sha': B, 'subject': 'subject'}]})
        self.assertEqual([c[1] for c in calls], ['repos/o/r/compare/' + A + '...' + B])

    def test_an_unavailable_diff_is_compared_on_the_branch_in_reverse(self):
        C = 'c' * 40
        # The branch at B is two commits ahead of the pin A: GraphQL reports A behind.
        run, calls = self.runner(RuntimeError(self.DIFF_ERROR),
                                 self.branch(B, 'BEHIND', 0, 2, history=[B, C, A]))
        self.assertEqual(lib.compare('o/r', A, B, branch='main', run=run),
                         {'status': 'ahead', 'ahead_by': 2, 'behind_by': 0,
                          'commits': [{'sha': C, 'subject': 'commit c'},
                                      {'sha': B, 'subject': 'commit b'}]})
        self.assertIn('-f', calls[1])
        self.assertIn('ref=refs/heads/main', calls[1])
        self.assertIn('base=' + A, calls[1])
        for graphql, rest in [('AHEAD', 'behind'), ('DIVERGED', 'diverged'), ('IDENTICAL', 'identical')]:
            run, _ = self.runner(RuntimeError(self.DIFF_ERROR), self.branch(B, graphql, 3, 1))
            relation = lib.compare('o/r', A, B, branch='main', run=run)
            self.assertEqual((relation['status'], relation['ahead_by'], relation['behind_by']), (rest, 1, 3))

    def test_a_branch_that_moved_or_vanished_is_not_compared(self):
        run, _ = self.runner(RuntimeError(self.DIFF_ERROR), self.branch('c' * 40, 'BEHIND', 0, 2))
        with self.assertRaisesRegex(RuntimeError, 'moved'):
            lib.compare('o/r', A, B, branch='main', run=run)
        run, _ = self.runner(RuntimeError(self.DIFF_ERROR), {'data': {'repository': {'ref': None}}})
        with self.assertRaisesRegex(RuntimeError, 'not found'):
            lib.compare('o/r', A, B, branch='main', run=run)

    def test_other_failures_and_branchless_comparisons_still_fail(self):
        run, calls = self.runner(RuntimeError('gh api failed: Not Found (HTTP 404)'))
        with self.assertRaisesRegex(RuntimeError, '404'):
            lib.compare('o/r', A, B, branch='main', run=run)
        run, calls = self.runner(RuntimeError(self.DIFF_ERROR))
        with self.assertRaisesRegex(RuntimeError, 'diff'):
            lib.compare('o/r', A, B, run=run)
        self.assertEqual(len(calls), 1)

    def test_an_unavailable_diff_is_not_retried(self):
        sleeps = []
        failure = subprocess.CompletedProcess([], 1, '', self.DIFF_ERROR)
        original = subprocess.run
        subprocess.run = lambda *args, **kwargs: failure
        try:
            with self.assertRaisesRegex(RuntimeError, 'diff'):
                lib.gh('api', 'repos/o/r/compare/x...y', sleep=sleeps.append)
        finally:
            subprocess.run = original
        self.assertEqual(sleeps, [])


if __name__ == '__main__':
    unittest.main()
