import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('r2_cache_mirror',
    Path(__file__).resolve().parents[1]/'scripts/r2-cache-mirror.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# A real entry of the live cache: the 599-byte NAR of unit-systemd-localed.service
# in cache-testing-20261018.2, whose sha256 was computed from the downloaded file.
FILE_HASH = '0cnyr6krn33ymivs46c9a62sj5q5s4bp7vd8ibzq4zv3xlmmv44b'
FILE_SHA256 = '8b905d2bed637f82ff8aa8ed7317d10517a985518919a277ac7e0c9ba7c9de32'
RELEASE = 'https://github.com/aurora-silicon/nixos-aurora/releases/download/cache-testing-20261018.2'
NAME = '00g6x5iwc7lc6d4nq7h8kpdgl6fn85vl.narinfo'
TEXT = (f'StorePath: /nix/store/00g6x5iwc7lc6d4nq7h8kpdgl6fn85vl-unit-systemd-localed.service\n'
        f'URL: {RELEASE}/{FILE_HASH}.nar.zst\nCompression: zstd\nFileHash: sha256:{FILE_HASH}\n'
        'FileSize: 599\nNarHash: sha256:0q08r59vmvsfpri47sw59517gqimgdqi0z24dfnw4m7xq7a46j1m\nNarSize: 1304\n'
        'References: 8w0qabyr98chcmr4y9hh6h6l26albldx-systemd-261.3\n'
        'Deriver: y4nl68azh5735sr4vysd8ldyvd70msf5-unit-systemd-localed.service.drv\n'
        'Sig: aurora-nixos-1:gJdnzsegH2tA3aTWji/uuibVoKD/3mRg1cqGTBr6i9rfelbBVkcZcwnzt9Oaq+PN0PqM/CvThZWG9mvUsG3iAA==\n')


class R2CacheMirrorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root/'cache'
        self.cache.mkdir()
        (self.cache/'nix-cache-info').write_text('StoreDir: /nix/store\nWantMassQuery: 1\nPriority: 41\n')
        (self.cache/NAME).write_text(TEXT)

    def test_decodes_nix_base32_like_nix(self):
        self.assertEqual(module.nix32_decode(FILE_HASH).hex(), FILE_SHA256)
        with self.assertRaises(ValueError):
            module.nix32_decode('z' * 52)

    def test_rewrites_only_the_url_and_lists_the_release_source(self):
        result = module.plan(self.cache, self.root/'out')
        written = (self.root/'out/cache'/NAME).read_text()
        self.assertEqual(written, TEXT.replace(f'{RELEASE}/', 'nar/'))
        self.assertIn('Sig: aurora-nixos-1:', written)
        self.assertEqual(result['nars'], [{
            'key': f'nar/{FILE_HASH}.nar.zst', 'name': f'{FILE_HASH}.nar.zst', 'size': 599, 'sha256': FILE_SHA256,
            'source': {'repository': 'aurora-silicon/nixos-aurora', 'tag': 'cache-testing-20261018.2'}}])
        self.assertEqual([item['key'] for item in result['metadata']], [NAME, 'nix-cache-info'])
        self.assertTrue(all('no-transform' in item['cache_control'] for item in result['metadata']))
        self.assertEqual(json.loads((self.root/'out/plan.json').read_text()), result)

    def test_shared_nar_is_copied_once(self):
        other = 'b' * 32 + '.narinfo'
        (self.cache/other).write_text(TEXT.replace('00g6x5iwc7lc6d4nq7h8kpdgl6fn85vl', 'b' * 32))
        result = module.plan(self.cache, self.root/'out')
        self.assertEqual(len(result['nars']), 1)
        self.assertEqual(len(result['metadata']), 3)

    def test_refuses_foreign_or_mismatched_urls(self):
        cases = {
            'foreign host': TEXT.replace(RELEASE, 'https://example.org/cache-testing-20261018.2'),
            'other repository': TEXT.replace('aurora-silicon/nixos-aurora', 'aurora-silicon/fedora-aurora'),
            'name is not the FileHash': TEXT.replace(f'/{FILE_HASH}.nar.zst', '/' + 'a' * 52 + '.nar.zst'),
            'compression mismatch': TEXT.replace('Compression: zstd', 'Compression: xz'),
            'already relative': TEXT.replace(f'{RELEASE}/', 'nar/'),
        }
        for label, text in cases.items():
            with self.subTest(label):
                (self.cache/NAME).write_text(text)
                with self.assertRaises(ValueError):
                    module.plan(self.cache, self.root/label.replace(' ', '-'))

    def test_refuses_unsafe_names_and_an_existing_output(self):
        (self.cache/'x.narinfo').write_text(TEXT)
        with self.assertRaises(ValueError):
            module.plan(self.cache, self.root/'out')
        (self.cache/'x.narinfo').unlink()
        module.plan(self.cache, self.root/'again')
        with self.assertRaises(SystemExit):
            module.plan(self.cache, self.root/'again')

    def test_upload_requires_credentials(self):
        module.plan(self.cache, self.root/'out')
        saved = {name: module.os.environ.pop(name, None)
                 for name in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'R2_ACCOUNT_ID', 'R2_BUCKET', 'GH_TOKEN')}
        self.addCleanup(lambda: module.os.environ.update({k: v for k, v in saved.items() if v is not None}))
        with self.assertRaises(SystemExit):
            module.upload(self.root/'out/plan.json', self.root/'out/cache', self.root/'work', 1)


if __name__ == '__main__':
    unittest.main()
