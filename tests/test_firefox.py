"""Firefox: nixpkgs' Firefox with the RDD V4L2 Request patch."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'patches' / 'firefox-rdd-v4l2-request.patch'


class FirefoxTests(unittest.TestCase):
    def test_overlay_patches_the_unwrapped_browser_that_programs_firefox_wraps(self):
        overlay = (ROOT / 'overlay.nix').read_text()
        self.assertRegex(overlay, r'firefox-unwrapped = prev\.firefox-unwrapped\.overrideAttrs \(old: \{\n'
                                  r'\s+patches = \(old\.patches or \[ \]\) \+\+ '
                                  r'\[ \(stableFile \./patches/firefox-rdd-v4l2-request\.patch\) \];')
        self.assertIn('programs.firefox.enable', (ROOT / 'modules' / 'aurora.nix').read_text())

    def test_ci_builds_and_caches_it(self):
        self.assertRegex((ROOT / 'flake.nix').read_text(), r'(?m)^\s+firefox = pkgs\.firefox-unwrapped;$')
        self.assertIn("'firefox': []", (ROOT / 'scripts' / 'prefetch-sources.py').read_text())
        self.assertIn("matrix.package == 'firefox' && 355", (ROOT / '.github/workflows/checks.yml').read_text())

    def test_seccomp_admits_exactly_four_media_ioctls(self):
        patch = PATCH.read_text()
        added = ''.join(line[1:] for line in patch.splitlines(True)
                        if line.startswith('+') and not line.startswith('+++'))
        rule = re.search(r'\.ElseIf\(AnyOf\((.*?)\),\s*Allow\(\)\)', added, re.S)
        self.assertEqual(re.findall(r'request == (\w+)', rule[1]),
                         ['MEDIA_IOC_G_TOPOLOGY', 'MEDIA_IOC_REQUEST_ALLOC',
                          'MEDIA_REQUEST_IOC_QUEUE', 'MEDIA_REQUEST_IOC_REINIT'])
        self.assertIn('aM2mDevices.Contains(', patch)


if __name__ == '__main__':
    unittest.main()
