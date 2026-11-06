"""Offline Nix cache interoperability; requires Nix, Git, OpenSSL and localhost.

Run separately from the source tracker's tool-only tests:
  nix shell --inputs-from . nixpkgs#openssl -c python3 -m unittest discover -s tests/integration
"""
from contextlib import contextmanager
from functools import partial
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import cache_inputs


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


signer = load('integration_signer', 'sign-cache-metadata.py')
publication = load('integration_publication', 'prepare-cache-publication.py')
verifier = load('integration_http_verifier', 'verify-published-cache.py')
channels = load('integration_channels', 'cache-channels.py')


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@contextmanager
def serve(directory):
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(directory)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class RealCacheLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [tool for tool in ('nix', 'git', 'openssl') if shutil.which(tool) is None]
        if missing:
            raise RuntimeError('Cache integration tests require: ' + ', '.join(missing))
        if not Path('/bin/sh').is_file():
            raise RuntimeError('The tiny offline fixture requires /bin/sh')

    def command(self, *args, cwd=None):
        return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.PIPE).strip()

    def git(self, *args):
        return self.command('git', '-C', str(self.repo), '-c', 'user.name=Cache test',
                            '-c', 'user.email=cache-test@example.invalid', '-c', 'commit.gpgsign=false', *args)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='aurora-cache-integration-')))
        self.repo = self.root / 'repository'
        self.repo.mkdir()
        self.enterContext(patch.dict(os.environ, {
            'NIX_CONFIG': '\n'.join([
                'experimental-features = nix-command flakes',
                'store = local?root=' + str(self.root / 'store'),
                'sandbox = false', 'substituters =', 'build-users-group =',
                'warn-dirty = false', 'max-jobs = 1',
            ]),
            'XDG_CACHE_HOME': str(self.root / 'cache'),
            'XDG_CONFIG_HOME': str(self.root / 'config'),
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
        }))
        # No inputs, downloads or hardware code: one shell printf produces an
        # input-addressed store path, so Nix must actually check its signature.
        system = self.command('nix', 'eval', '--impure', '--raw', '--expr', 'builtins.currentSystem')
        (self.repo / 'flake.nix').write_text('''{
  outputs = { ... }: {
    packages.aarch64-linux.fixture = builtins.derivation {
      name = "aurora-cache-fixture";
      outputs = [ "out" ];
      system = ''' + json.dumps(system) + ''';
      builder = "/bin/sh";
      args = [ "-c" "printf cache-fixture > $out" ];
    };
  };
}
''')
        (self.repo / 'keys').mkdir()
        (self.repo / 'scripts').mkdir()
        for filename in ('extract-cache-metadata.py', 'verify-published-cache.py'):
            shutil.copyfile(ROOT / 'scripts' / filename, self.repo / 'scripts' / filename)
        secret = self.root / 'secret.key'
        signer.generate_dry_run_key(secret, self.repo / 'keys/cache.pub')
        self.public = (self.repo / 'keys/cache.pub').read_text()
        self.git('init', '-q', '-b', 'main')
        self.git('add', '.')
        self.git('commit', '-qm', 'tiny cache fixture')
        self.commit = self.git('rev-parse', 'HEAD')
        self.git('remote', 'add', 'origin', self.repo.as_uri())
        self.git('update-ref', 'refs/remotes/origin/main', self.commit)
        self.enterContext(patch.object(cache_inputs, 'ROOT', self.repo))
        self.enterContext(patch.object(channels, 'ROOT', self.repo))
        reference = 'git+' + self.repo.as_uri() + '?rev=' + self.commit
        build = json.loads(self.command('nix', 'build', '--no-link', '--json', reference + '#packages.aarch64-linux.fixture'))
        self.expected = cache_inputs.expected_outputs(self.commit)
        self.assertEqual(self.expected['fixture']['drvPath'], build[0]['drvPath'])
        self.source = self.root / 'unsigned-cache'
        self.command('bash', str(ROOT / 'scripts/export-cache'), str(self.source), build[0]['outputs']['out'])
        metadata = self.root / 'metadata'
        metadata.mkdir()
        for entry in self.source.glob('*.narinfo'):
            self.assertNotIn('\nCA:', entry.read_text(), 'fixture must need a signature, not self-authenticate')
            shutil.copyfile(entry, metadata / entry.name)
        shutil.copyfile(self.source / 'nix-cache-info', metadata / 'nix-cache-info')
        self.assertEqual(signer.sign(metadata, secret.read_text(), self.public), 1)
        self.assertEqual(signer.verify(metadata, self.public), 1)
        for entry in metadata.glob('*.narinfo'):
            shutil.copyfile(entry, self.source / entry.name)
        self.output = self.root / 'publication'
        # Substitute only the GitHub release transport boundary. NAR contents,
        # metadata signatures, preparation, extraction and Nix verification run
        # unchanged against two local HTTP servers.
        self.base = self.enterContext(serve(self.output / 'assets'))
        self.enterContext(patch.object(publication, 'BASE', re.escape(self.base)))
        publication.prepare(self.source, self.output, self.base, commit=self.commit, expected=self.expected)
        assets = self.output / 'assets'
        rows = [(entry.name, hashlib.sha256(entry.read_bytes()).hexdigest())
                for entry in sorted(assets.iterdir()) if entry.is_file()]
        (assets / 'SHA256SUMS').write_text(''.join(f'{digest}  {name}\n' for name, digest in rows))
        self.attestation = [{'verificationResult': {'statement': {'subject': [
            {'name': name, 'digest': {'sha256': digest}} for name, digest in rows]}}}]

    def test_real_signed_cache_roundtrip_rejects_wrong_key_and_corrupt_nar(self):
        verifier.verify(self.output / 'site/cache', self.public)
        other = self.root / 'other.key'
        other_public = self.root / 'other.pub'
        signer.generate_dry_run_key(other, other_public, name='untrusted-test-key')
        with self.assertRaises(subprocess.CalledProcessError):
            verifier.verify(self.output / 'site/cache', other_public.read_text())
        next((self.output / 'assets').glob('*.nar.*')).write_bytes(b'corrupted NAR transport')
        with self.assertRaises(subprocess.CalledProcessError):
            verifier.verify(self.output / 'site/cache', self.public)

    @contextmanager
    def github_boundary(self):
        assets = self.output / 'assets'
        release = {'tag_name': 'cache-test', 'target_commitish': self.commit,
                   'created_at': '2026-01-01T00:00:00Z'}
        original_run = subprocess.run

        def run(command, *args, **kwargs):
            if command[:3] == ['gh', 'attestation', 'verify']:
                self.assertEqual(command[command.index('--repo') + 1], 'aurora-silicon/nixos-aurora')
                self.assertEqual(command[command.index('--signer-workflow') + 1],
                                 'aurora-silicon/nixos-aurora/.github/workflows/publish-cache.yml')
                self.assertIn('--deny-self-hosted-runners', command)
                self.assertTrue(kwargs['check'])
                return subprocess.CompletedProcess(command, 0, json.dumps(self.attestation), '')
            return original_run(command, *args, **kwargs)

        def download(*args, **kwargs):
            self.assertEqual(args[:3], ('release', 'download', 'cache-test'))
            destination = Path(args[args.index('--dir') + 1])
            for name in ('cache-metadata.tar.gz', 'manifest.json', 'SHA256SUMS'):
                shutil.copyfile(assets / name, destination / name)
            return subprocess.CompletedProcess(args, 0, '', '')

        def api(route):
            if route.endswith('/releases/tags/cache-test'):
                return release
            if route.endswith('/releases?per_page=100'):
                return [release]
            self.fail('Unexpected GitHub route: ' + route)

        with patch.object(channels.lib, 'gh', side_effect=download), \
             patch.object(channels.lib, 'gh_api', side_effect=api), \
             patch.object(channels.subprocess, 'run', side_effect=run):
            yield

    def test_authenticate_and_assemble_use_real_files_git_and_nix(self):
        with self.github_boundary():
            admitted, provenance = channels.authenticate_release(
                'aurora-silicon/nixos-aurora', 'cache-test', self.root / 'admitted', self.root / 'auth-work')
            self.assertEqual((admitted['target_commitish'], provenance), (self.commit, 'verified'))
            state_path = self.root / 'next-state.json'
            channels.assemble(SimpleNamespace(
                repository='aurora-silicon/nixos-aurora', tag='cache-test', site=str(self.root / 'site'),
                work=str(self.root / 'assemble-work'), state_out=str(state_path),
                allow_downgrade=False, advance_testing=True,
            ))
        state = json.loads(state_path.read_text())
        self.assertEqual(state['channels']['testing']['commit'], self.commit)
        self.assertEqual(state['cache']['tag'], 'cache-test')
        self.assertEqual(state['cache']['provenance'], 'verified')
        before = next((self.output / 'site/cache').glob('*.narinfo')).read_bytes()
        after = next((self.root / 'site/cache').glob('*.narinfo')).read_bytes()
        self.assertEqual(after, before)
        self.assertEqual((self.root / 'site/cache.pub').read_text(), self.public)

    def test_release_digest_and_attestation_fail_before_extraction(self):
        manifest = self.output / 'assets/manifest.json'
        original = manifest.read_bytes()
        with self.github_boundary():
            manifest.write_bytes(original + b'\n')
            with self.assertRaisesRegex(ValueError, 'SHA256SUMS does not match manifest.json'):
                channels.authenticate_release('aurora-silicon/nixos-aurora', 'cache-test',
                                              self.root / 'bad-digest-site', self.root / 'bad-digest-work')
            self.assertFalse((self.root / 'bad-digest-site').exists())
            manifest.write_bytes(original)
            self.attestation = []
            with self.assertRaisesRegex(ValueError, 'provenance attestation does not cover'):
                channels.authenticate_release('aurora-silicon/nixos-aurora', 'cache-test',
                                              self.root / 'bad-provenance-site', self.root / 'bad-provenance-work')
            self.assertFalse((self.root / 'bad-provenance-site').exists())


if __name__ == '__main__':
    unittest.main()
