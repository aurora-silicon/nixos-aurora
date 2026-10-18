import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('cache_publication',
    Path(__file__).resolve().parents[1]/'scripts/prepare-cache-publication.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
BASE = 'https://github.com/aurora-silicon/nixos-aurora/releases/download/cache-testing-previous'


class CachePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root/'source'
        self.previous = self.root/'previous'
        (self.source/'nar').mkdir(parents=True)
        self.previous.mkdir()
        (self.source/'nix-cache-info').write_text('StoreDir: /nix/store\n')
        (self.source/'nar/abc.nar.zst').write_bytes(b'compressed nar fixture')
        self.name = 'a'*32+'.narinfo'
        self.text = ('StorePath: /nix/store/'+'a'*32+'-fixture\nURL: nar/abc.nar.zst\n'
                     'Compression: zstd\nFileHash: sha256:transport\nFileSize: 22\n'
                     'NarHash: sha256:nar\nNarSize: 40\nReferences: \nSig: test:current-signature\n')
        (self.source/self.name).write_text(self.text)
        (self.previous/self.name).write_text(self.text.replace('nar/abc.nar.zst', BASE+'/abc.nar.zst')
                                            .replace('current-signature', 'previous-signature'))

    def prepare(self):
        return module.prepare(self.source, self.root/'output',
            BASE.replace('previous', 'next'), self.previous)

    def test_reuses_exact_transport_but_keeps_current_signature_and_older_entries(self):
        older = self.previous/('b'*32+'.narinfo')
        older.write_text((self.previous/self.name).read_text().replace('a'*32, 'b'*32))
        records = self.prepare()
        self.assertEqual(records[0]['reused_from'], BASE+'/abc.nar.zst')
        self.assertFalse((self.root/'output/assets/abc.nar.zst').exists())
        current = (self.root/'output/site/cache'/self.name).read_text()
        self.assertIn('Sig: test:current-signature', current)
        self.assertIn(BASE+'/abc.nar.zst', current)
        self.assertEqual((self.root/'output/site/cache'/older.name).read_bytes(), older.read_bytes())

    def test_conflicting_signed_identity_is_rejected(self):
        path = self.previous/self.name
        path.write_text(path.read_text().replace('NarHash: sha256:nar', 'NarHash: sha256:other'))
        with self.assertRaisesRegex(ValueError, 'conflicting signed store identity'):
            self.prepare()

    def test_foreign_transport_is_republished_at_our_release(self):
        path = self.previous/self.name
        path.write_text(path.read_text().replace('github.com/', 'github.com.attacker.invalid/'))
        records = self.prepare()
        self.assertNotIn('reused_from', records[0])
        self.assertEqual((self.root/'output/assets/abc.nar.zst').read_bytes(), b'compressed nar fixture')
        self.assertIn(BASE.replace('previous', 'next')+'/abc.nar.zst',
                      (self.root/'output/site/cache'/self.name).read_text())

    def test_changed_compression_bytes_are_not_reused(self):
        path = self.previous/self.name
        path.write_text(path.read_text().replace('FileHash: sha256:transport', 'FileHash: sha256:older'))
        self.assertNotIn('reused_from', self.prepare()[0])
        self.assertTrue((self.root/'output/assets/abc.nar.zst').is_file())


if __name__ == '__main__':
    unittest.main()
