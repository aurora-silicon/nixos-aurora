import base64
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sign_cache_metadata', ROOT / 'scripts/sign-cache-metadata.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# Published by cache-testing-20261018.2 and signed by the production key in
# keys/cache.pub: it pins Nix's fingerprint format.
PUBLISHED = 'StorePath: /nix/store/00g6x5iwc7lc6d4nq7h8kpdgl6fn85vl-unit-systemd-localed.service\nURL: https://github.com/aurora-silicon/nixos-aurora/releases/download/cache-testing-20261018.2/0cnyr6krn33ymivs46c9a62sj5q5s4bp7vd8ibzq4zv3xlmmv44b.nar.zst\nCompression: zstd\nFileHash: sha256:0cnyr6krn33ymivs46c9a62sj5q5s4bp7vd8ibzq4zv3xlmmv44b\nFileSize: 599\nNarHash: sha256:0q08r59vmvsfpri47sw59517gqimgdqi0z24dfnw4m7xq7a46j1m\nNarSize: 1304\nReferences: 11ra19d3cyh5kv0lk8v35wqcnz6wjrm0-findutils-4.11.0 2jk00rxplr3qjmjl2q46l7izbf8gxcs6-gnused-4.10 5g0149dc72bz1rdxjc10qnr4vdh9yp1x-tzdata-2026d 82643wb56lminz3a4b6gk92d2g4ydwks-gnugrep-3.12 8w0qabyr98chcmr4y9hh6h6l26albldx-systemd-261.3 dq1apsyiah48nmc4n45dpwc33k887hdn-coreutils-9.11 p6anq44imf9jm477g3q1ari69c6lrhdf-glibc-locales-2.44-25\nDeriver: y4nl68azh5735sr4vysd8ldyvd70msf5-unit-systemd-localed.service.drv\nSig: aurora-nixos-1:gJdnzsegH2tA3aTWji/uuibVoKD/3mRg1cqGTBr6i9rfelbBVkcZcwnzt9Oaq+PN0PqM/CvThZWG9mvUsG3iAA==\n'


@unittest.skipUnless(shutil.which('openssl'), 'openssl is required')
class SignCacheMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.metadata = self.root / 'metadata'
        self.metadata.mkdir()
        (self.metadata / '00g6x5iwc7lc6d4nq7h8kpdgl6fn85vl.narinfo').write_text(PUBLISHED)
        (self.metadata / 'nix-cache-info').write_text('StoreDir: /nix/store\n')

    def key(self):
        module.generate_dry_run_key(self.root / 'secret', self.root / 'public.pub')
        return (self.root / 'secret').read_text(), (self.root / 'public.pub').read_text()

    def test_production_signature_verifies_with_the_committed_key(self):
        self.assertEqual(module.verify(self.metadata, (ROOT / 'keys/cache.pub').read_text()), 1)

    def test_sign_adds_one_signature_and_keeps_others(self):
        secret, public = self.key()
        self.assertEqual(module.sign(self.metadata, secret, public), 1)
        module.sign(self.metadata, secret, public)
        self.assertEqual(module.verify(self.metadata, public), 1)
        self.assertEqual(module.verify(self.metadata, (ROOT / 'keys/cache.pub').read_text()), 1)
        text = (self.metadata / '00g6x5iwc7lc6d4nq7h8kpdgl6fn85vl.narinfo').read_text()
        self.assertEqual(text.count('Sig: aurora-dry-run-1:'), 1)

    def test_a_key_that_is_not_the_committed_public_key_is_refused(self):
        secret, _ = self.key()
        with self.assertRaisesRegex(ValueError, 'committed public key'):
            module.sign(self.metadata, secret, (ROOT / 'keys/cache.pub').read_text())

    def test_tampered_metadata_fails_verification(self):
        path = self.metadata / '00g6x5iwc7lc6d4nq7h8kpdgl6fn85vl.narinfo'
        path.write_text(PUBLISHED.replace('NarSize: 1304', 'NarSize: 1305'))
        with self.assertRaises(Exception):
            module.verify(self.metadata, (ROOT / 'keys/cache.pub').read_text())

    def test_malformed_metadata_is_rejected(self):
        with self.assertRaises(ValueError):
            module.parse('StorePath: /nix/store/x\nNarHash: sha256:abc\nNarSize: 1\n')


if __name__ == '__main__':
    unittest.main()
