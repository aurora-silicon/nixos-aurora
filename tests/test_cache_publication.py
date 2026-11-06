import importlib.util
import json
from pathlib import Path
import subprocess
import sys
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

    def reuse(self, expected):
        (self.previous / 'nix-cache-info').write_text('StoreDir: /nix/store\n')
        return module.prepare(None, self.root / 'output', BASE.replace('previous', 'next'),
                              self.previous, commit='c' * 40, expected=expected)

    def test_metadata_only_release_preserves_signatures_and_transports_without_new_nars(self):
        expected = {'kernel': {'outputs': ['/nix/store/' + 'a' * 32 + '-fixture']}}
        original = (self.previous / self.name).read_bytes()
        records = self.reuse(expected)
        self.assertEqual((self.root / 'output/site/cache' / self.name).read_bytes(), original)
        self.assertEqual(records[0]['reused_from'], BASE + '/abc.nar.zst')
        self.assertEqual(list((self.root / 'output/assets').glob('*.nar.*')), [])
        manifest = json.loads((self.root / 'output/assets/manifest.json').read_text())
        self.assertEqual(manifest['commit'], 'c' * 40)
        self.assertTrue((self.root / 'output/assets/cache-metadata.tar.gz').is_file())

    def test_metadata_reuse_rejects_incomplete_current_hardware_coverage(self):
        with self.assertRaisesRegex(ValueError, 'omits current hardware outputs: new-package'):
            self.reuse({'new-package': {'outputs': ['/nix/store/' + 'b' * 32 + '-missing']}})

    def test_metadata_reuse_rejects_foreign_nar_transports(self):
        path = self.previous / self.name
        path.write_text(path.read_text().replace('github.com/', 'foreign.invalid/'))
        with self.assertRaisesRegex(ValueError, 'unexpected reused NAR transport'):
            self.reuse({})

    def test_reuse_without_metadata_is_rejected_before_creating_output(self):
        with self.assertRaisesRegex(ValueError, 'requires a previous cache snapshot'):
            module.prepare(None, self.root / 'output', BASE)
        self.assertFalse((self.root / 'output').exists())

    def test_cli_rejects_ignored_or_incomplete_reuse_arguments_before_nix_evaluation(self):
        common = ['--output', str(self.root / 'output'), '--asset-base', BASE]
        cases = [
            (['--reuse-metadata', 'previous', '--previous-metadata', 'other', '--base-release', 'cache-old'],
             'cannot be combined'),
            (['--cache', 'source', '--base-release', 'cache-old'], 'only used with'),
            (['--reuse-metadata', 'previous'], 'requires --base-release'),
            (['--reuse-metadata', 'previous', '--base-release', 'main'], 'cache-* release'),
        ]
        script = Path(__file__).resolve().parents[1] / 'scripts/prepare-cache-publication.py'
        for args, message in cases:
            with self.subTest(args=args):
                # There is no Git checkout here. Validation must not invoke Git
                # or Nix before reporting the inconsistent argument set.
                result = subprocess.run([sys.executable, str(script), *common, *args],
                                        cwd=self.root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(message, result.stderr)
        self.assertFalse((self.root / 'output').exists())


if __name__ == '__main__':
    unittest.main()
