import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class XartPackageTests(unittest.TestCase):
    def test_the_touch_id_reset_is_pinned_built_and_installed(self):
        pin = json.loads((ROOT / 'sources.json').read_text())['aurora-xart']
        self.assertRegex(pin['commit'], r'^[0-9a-f]{40}$')
        self.assertTrue(pin['source_url'].endswith(pin['commit']))
        self.assertTrue(pin['nix_hash'].startswith('sha256-'))
        overlay = (ROOT / 'overlay.nix').read_text()
        recipe = overlay.split('  aurora-xart = ', 1)[1].split('\n  };\n', 1)[0]
        self.assertIn('src = source "aurora-xart";', recipe)
        self.assertIn('make check PYTHON=${final.python3.interpreter}', recipe)
        self.assertIn('#!${final.python3.interpreter} -I', recipe)
        self.assertRegex((ROOT / 'flake.nix').read_text(), r'(?m)^\s+xart = pkgs\.aurora-xart;$')
        spec = importlib.util.spec_from_file_location('prefetch', ROOT / 'scripts/prefetch-sources.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.NEEDS['xart'], ['aurora-xart'])
        sep = (ROOT / 'modules/sep.nix').read_text()
        self.assertTrue(re.search(r'environment\.systemPackages = \[[^]]*pkgs\.aurora-xart', sep))

    def test_the_docs_name_the_packaged_tool(self):
        for doc in ('README.md', 'XART-SAFETY.md'):
            text = (ROOT / 'sep' / doc).read_text()
            self.assertNotIn('install-aurora-sep.sh --reset-touchid', text)
            self.assertIn('aurora-xart reset-touchid', text)


if __name__ == '__main__':
    unittest.main()
