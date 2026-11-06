import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prefetch_sources', ROOT / 'scripts/prefetch-sources.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PrefetchSourcesTests(unittest.TestCase):
    def setUp(self):
        self.archives = module.archives()
        self.pins = json.loads((ROOT / 'sources.json').read_text())

    def test_vendored_helpers_and_patched_nixpkgs_packages_need_no_aurora_archives(self):
        self.assertEqual(module.select_sources(['sep', 'plymouth', 'docker'], self.archives), [])
        with self.assertRaisesRegex(ValueError, 'Unknown flake packages: typo'):
            module.select_sources(['typo'], self.archives)

    def test_userpages_and_steam_fetch_only_their_pinned_sources(self):
        self.assertEqual(module.select_sources(['userpages'], self.archives), ['kernel-aurora'])
        self.assertEqual(module.select_sources(['steam'], self.archives), ['aurora-steam-native'])

    def test_fex_prefetches_every_gitlink_under_the_exact_fetchurl_names(self):
        keys = module.select_sources(['fex'], self.archives)
        expected = ['fex-emu'] + ['fex-emu/' + name for name in self.pins['fex-emu']['extra_sources']]
        self.assertEqual(keys, sorted(expected))
        pin = self.pins['fex-emu']
        name, urls, digest = self.archives['fex-emu']
        self.assertEqual(name, f'fex-{pin["commit"]}.tar.gz')
        self.assertEqual(urls[-1], pin['source_url'])
        self.assertEqual(urls[0].rsplit('/', 1)[-1], f'fex-emu-{pin["commit"]}.tar.gz')
        self.assertEqual(digest, pin['sha256'])
        for dependency, record in pin['extra_sources'].items():
            name, urls, digest = self.archives['fex-emu/' + dependency]
            self.assertEqual(name, f'{dependency}-{record["commit"]}.tar.gz')
            self.assertEqual(urls[-1], record['source_url'])
            self.assertEqual(digest, record['sha256'])

    def test_companion_sources_expand_without_prefetching_unrelated_archives(self):
        self.assertEqual(module.select_sources(['mil-hwx-compiler'], self.archives),
                         ['mil-hwx-compiler', 'mil-hwx-compiler/gnustep-base'])
        for key in ('mil-hwx-compiler', 'omarchy-ane-tools'):
            self.assertEqual(self.archives[key][1], [self.pins[key]['source_url']])

    def test_proton_prefetches_exact_manifest_archives(self):
        manifest = json.loads((ROOT / 'pkgs/proton/sources.json').read_text())
        selected = module.select_sources(['proton'], self.archives)
        self.assertEqual(selected, sorted('proton/' + key for key in manifest['archives']))
        for key, record in manifest['archives'].items():
            name, urls, digest = self.archives['proton/' + key]
            self.assertEqual((name, urls), (record['name'], [record['url']]))
            self.assertEqual(module.lib.sri_from_hex(digest), record['hash'])


if __name__ == '__main__':
    unittest.main()
