import datetime
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('track_sources', ROOT / 'scripts/track-sources.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
NEW = 'c' * 40
TODAY = datetime.date(2026, 10, 23)


class NixPinTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('kernel', 'locks'):
            shutil.copytree(ROOT / name, self.root / name)
        for name in ('overlay.nix', 'mesa.nix', 'sources.json'):
            shutil.copyfile(ROOT / name, self.root / name)
        self.pins = json.loads((ROOT / 'sources.json').read_text())

    def archive(self, files):
        path = self.root / 'source.tar.gz'
        with tarfile.open(path, 'w:gz') as tar:
            for name, data in files.items():
                info = tarfile.TarInfo('aura-x/' + name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return str(path)

    def item(self, key, **extra):
        return {'key': key, 'old': self.pins[key]['commit'], 'new': NEW,
                'previous_version': self.pins[key].get('version'), **extra}

    def test_kernel_commit_and_version_follow_the_pin(self):
        old = self.pins['kernel-aurora']['version']
        item = self.item('kernel-aurora', version='7.9.0', version_changed=True)
        notes = module.update_recipe(self.root, item, TODAY)
        self.assertIn(NEW, (self.root / 'kernel/provenance.json').read_text())
        overlay = (self.root / 'overlay.nix').read_text()
        self.assertIn('version = "7.9.0";', overlay)
        self.assertIn('modDirVersion = "7.9.0";', overlay)
        self.assertIn('extraMeta.branch = "7.9";', overlay)
        self.assertNotIn(f'version = "{old}";', overlay)
        self.assertTrue(notes)

    def test_aura_lock_is_taken_from_the_archive_and_git_dependency_changes_need_review(self):
        current = (ROOT / 'locks/aura.Cargo.lock').read_text()
        item = self.item('aura', archive_path=self.archive({'rust/Cargo.lock': current.encode()}))
        self.assertEqual(module.update_recipe(self.root, item, TODAY), [])
        changed = current + '\n[[package]]\nname = "x"\nsource = "git+https://example.org/x?rev=1#1"\n'
        item = self.item('aura', archive_path=self.archive({'rust/Cargo.lock': changed.encode()}))
        module.update_recipe(self.root, item, TODAY)
        self.assertEqual((self.root / 'locks/aura.Cargo.lock').read_text(), changed)
        self.assertTrue(item.get('needs_review'))

    def test_a_release_label_is_dropped_when_aura_moves(self):
        overlay = self.root / 'overlay.nix'
        self.assertIn('AURA_VERSION_TAG', overlay.read_text())
        current = (ROOT / 'locks/aura.Cargo.lock').read_text().encode()
        item = self.item('aura', archive_path=self.archive({'rust/Cargo.lock': current}))
        module.update_recipe(self.root, item, TODAY)
        text = overlay.read_text()
        self.assertNotIn('AURA_VERSION_TAG', text)
        self.assertNotIn('release label', text)
        self.assertIn('makeFlags = [ "RELEASE=1" "CHAINLOADING=1" "BUILTIN_LOGO=aurora" ];\n    postBuild', text)

    def test_mesa_version_change_edits_the_recipe(self):
        item = self.item('mesa-aurora', version='26.9.0', version_changed=True)
        module.update_recipe(self.root, item, TODAY)
        self.assertIn('version = "26.9.0";', (self.root / 'mesa.nix').read_text())

    def test_tracked_sources_are_pinned_with_sri_hashes(self):
        tracking = json.loads((ROOT / 'tracking.json').read_text())
        for key in tracking['sources']:
            pin = self.pins[key]
            self.assertEqual(module.lib.sri_from_hex(pin['sha256']), pin['nix_hash'])


if __name__ == '__main__':
    unittest.main()
