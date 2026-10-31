"""The compiler's private Foundation must be prefetched under fetchurl's name."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ane_prefetch', ROOT / 'scripts/prefetch-sources.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class AneSourceTests(unittest.TestCase):
    def test_private_foundation_is_in_the_compiler_source_closure(self):
        sources = module.archives()
        self.assertLessEqual(set(module.NEEDS['mil-hwx-compiler']), set(sources))
        pin = json.loads((ROOT / 'sources.json').read_text())['mil-hwx-compiler']['extra_sources']['gnustep-base']
        name, urls, digest = sources['mil-hwx-compiler/gnustep-base']
        self.assertEqual(name, f'gnustep-base-{pin["commit"]}.tar.gz')
        self.assertEqual(urls, [pin['source_url']])
        self.assertEqual(digest, pin['sha256'])

if __name__ == '__main__':
    unittest.main()
