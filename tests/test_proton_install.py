import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WritableProtonInstall(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.root / 'store/Aurora-Proton-revision'
        self.source.mkdir(parents=True)
        (self.source / 'proton').write_text('pinned launcher\n')
        self.home = self.root / 'home'
        self.home.mkdir()
        self.data = self.home / 'data with spaces'
        self.target = self.data / 'aurora-proton' / self.source.name
        script = (ROOT / 'steam/prepare-proton').read_text().replace('@PROTON@', repr(str(self.source)))
        self.script = self.root / 'prepare'
        self.script.write_text(script)
        self.env = {**os.environ, 'HOME': str(self.home), 'XDG_DATA_HOME': str(self.data)}

    def run_installer(self):
        return subprocess.run([shutil.which('bash'), '-euo', 'pipefail', str(self.script)],
                              env=self.env, text=True, capture_output=True)

    def test_writable_revision_copy_preserves_user_settings_on_reentry(self):
        first = self.run_installer()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout.strip(), str(self.target))
        settings = self.target / 'user_settings.py'
        settings.write_text('user settings\n')
        second = self.run_installer()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(settings.read_text(), 'user settings\n')
        self.assertEqual((self.source / 'proton').read_text(), 'pinned launcher\n')
        self.assertFalse((self.source / 'user_settings.py').exists())

    def test_unmanaged_target_is_never_replaced(self):
        self.target.mkdir(parents=True)
        (self.target / 'mine').write_text('keep\n')
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.target / 'mine').read_text(), 'keep\n')
        self.assertFalse((self.target / 'proton').exists())


if __name__ == '__main__':
    unittest.main()
