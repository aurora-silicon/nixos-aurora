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
from unittest.mock import patch

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

    def test_kernel_update_refreshes_provenance_without_editing_recipes(self):
        recipes = {name: (self.root / name).read_text() for name in ('overlay.nix', 'mesa.nix')}
        item = self.item('kernel-aurora', version='7.9.0', version_changed=True)
        notes = module.update_recipe(self.root, item, TODAY)
        self.assertIn(NEW, (self.root / 'kernel/provenance.json').read_text())
        self.assertTrue(notes)
        for name, original in recipes.items():
            self.assertEqual((self.root / name).read_text(), original)
        self.assertFalse(item.get('needs_review'))

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
        # The planner also tests checkouts whose live pin has no release tag.
        pins = json.loads((self.root / 'sources.json').read_text())
        pins['aura']['release_tag'] = '1.0.0b1'
        (self.root / 'sources.json').write_text(json.dumps(pins, indent=2) + '\n')
        recipe = (self.root / 'overlay.nix').read_text()
        current = (ROOT / 'locks/aura.Cargo.lock').read_text().encode()
        item = self.item('aura', archive_path=self.archive({'rust/Cargo.lock': current}))
        module.update_recipe(self.root, item, TODAY)
        updated = json.loads((self.root / 'sources.json').read_text())
        self.assertNotIn('release_tag', updated['aura'])
        del pins['aura']['release_tag']
        self.assertEqual(updated, pins)
        self.assertEqual((self.root / 'overlay.nix').read_text(), recipe)
        text = (self.root / 'sources.json').read_text()
        module.update_recipe(self.root, item, TODAY)
        self.assertEqual((self.root / 'sources.json').read_text(), text)

    def test_mesa_version_change_needs_no_recipe_edit(self):
        original = (self.root / 'mesa.nix').read_text()
        item = self.item('mesa-aurora', version='26.9.0', version_changed=True)
        notes = module.update_recipe(self.root, item, TODAY)
        self.assertEqual((self.root / 'mesa.nix').read_text(), original)
        self.assertTrue(notes)
        self.assertFalse(item.get('needs_review'))

    def test_mesa_ci_includes_both_runtime_graphics_payloads(self):
        selected = module.ci_inputs(['kernel', 'mesa'])['checks.yml']['packages'].split()
        self.assertEqual(set(selected), {'kernel', 'mesa', 'fex-mesa', 'flatpak-gl', 'rusticl', 'lavapipe', 'graphics'})
        self.assertEqual(module.ci_inputs(['aura']), {'checks.yml': {'packages': 'aura'}})

    def fex_update(self):
        pins = json.loads((self.root / 'sources.json').read_text())
        item = self.item('fex-emu')
        pins['fex-emu']['commit'] = NEW
        (self.root / 'sources.json').write_text(json.dumps(pins, indent=2) + '\n')
        extras = pins['fex-emu']['extra_sources']
        modules = ''.join(f'[submodule "{name}"]\npath = {pin["path"]}\nurl = {pin["repository"]}\n'
                          for name, pin in extras.items())
        item['archive_path'] = self.archive({'.gitmodules': modules.encode()})
        tree = {'tree': [{'path': pin['path'], 'sha': pin['commit'], 'mode': '160000', 'type': 'commit'}
                         for pin in extras.values()]}
        return item, tree

    def test_fex_parent_pin_can_be_written_before_the_nested_sources(self):
        pins = json.loads((self.root / 'sources.json').read_text())
        pins['fex-emu'].update(commit=NEW, nix_hash='sha256-' + 'A' * 43 + '=')
        module.tl.write_pins(self.root, pins)
        self.assertEqual(json.loads((self.root / 'sources.json').read_text()), pins)

    def test_fex_changed_gitlink_refreshes_archive_identity_and_parent_marker(self):
        item, tree = self.fex_update()
        old = self.pins['fex-emu']['extra_sources']['cpp-optparse']
        next(entry for entry in tree['tree'] if entry['path'] == old['path'])['sha'] = 'd' * 40
        info = {'source_url': 'https://example.invalid/new.tar.gz', 'archive_root': 'new',
                'sha256': 'e' * 64, 'nix_hash': 'sha256-' + 'A' * 43 + '=', 'tree_verified': True}
        with patch.object(module.lib, 'gh_api', return_value=tree), \
             patch.object(module.tl, 'prepare_source', return_value=info) as prepare:
            notes = module.update_recipe(self.root, item, TODAY)
        updated = json.loads((self.root / 'sources.json').read_text())['fex-emu']
        self.assertEqual(updated['submodules_commit'], NEW)
        self.assertEqual(updated['extra_sources']['cpp-optparse']['commit'], 'd' * 40)
        self.assertEqual(updated['extra_sources']['cpp-optparse']['sha256'], info['sha256'])
        self.assertEqual(updated['extra_sources']['cpp-optparse']['path'], old['path'])
        self.assertEqual(prepare.call_count, 1)
        self.assertTrue(notes)
        self.assertFalse(item.get('needs_review'))

    def test_unverifiable_fex_gitlinks_leave_a_stale_marker_and_require_review(self):
        item, tree = self.fex_update()
        tree['truncated'] = True
        with patch.object(module.lib, 'gh_api', return_value=tree):
            module.update_recipe(self.root, item, TODAY)
        updated = json.loads((self.root / 'sources.json').read_text())['fex-emu']
        self.assertNotEqual(updated['submodules_commit'], updated['commit'])
        self.assertIn('truncated', item['needs_review'][0])

    def test_tracked_sources_are_pinned_with_sri_hashes(self):
        tracking = json.loads((ROOT / 'tracking.json').read_text())
        for key in tracking['sources']:
            pin = self.pins[key]
            self.assertEqual(module.lib.sri_from_hex(pin['sha256']), pin['nix_hash'])


if __name__ == '__main__':
    unittest.main()
