"""The shared negative checks in scripts/testlib.sh fail when they should."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'scripts/testlib.sh'


class TestlibTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def run_checks(self, body, **env):
        script = f'set -euo pipefail\nsource {LIB}\n{body}\necho REACHED\n'
        environment = dict(os.environ, **env)
        return subprocess.run(['bash', '-c', script], env=environment, cwd=self.dir,
                              capture_output=True, text=True)

    def assertPasses(self, body, **kwargs):
        result = self.run_checks(body, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('REACHED', result.stdout)

    def assertFails(self, body, **kwargs):
        result = self.run_checks(body, **kwargs)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('REACHED', result.stdout)
        return result

    def test_bare_negation_never_fails_under_set_e(self):
        # The reason for the helpers: the script runs on to the end.
        self.assertPasses('! true')

    def test_refute(self):
        self.assertPasses('refute false')
        self.assertIn('unexpected success: true', self.assertFails('refute true').stderr)

    def test_nomatch(self):
        (self.dir / 'ldd.txt').write_text('libc.so.6 => /usr/lib/libc.so.6\n')
        self.assertPasses("nomatch -F 'not found' ldd.txt")
        self.assertPasses("nomatch -x aurora-gl <<< 'flathub'")
        (self.dir / 'ldd.txt').write_text('libLLVM.so.21 => not found\n')
        self.assertIn('unexpected match', self.assertFails("nomatch -F 'not found' ldd.txt").stderr)
        self.assertFails("nomatch -x aurora-gl <<< 'aurora-gl'")
        # A missing file is a failure, not "no match".
        self.assertIn('grep failed (2)', self.assertFails("nomatch -F 'not found' missing.txt").stderr)


if __name__ == '__main__':
    unittest.main()
