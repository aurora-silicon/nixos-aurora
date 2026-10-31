"""A source pin is not blanket authorization to redistribute its archive."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('source_mirror_policy', ROOT / 'scripts/trackerlib.py')
tracker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tracker)

class SourceRedistributionTests(unittest.TestCase):
    def test_upstream_only_archives_are_not_queued_for_mirroring(self):
        pin = {'commit': 'a' * 40, 'sha256': 'b' * 64, 'source_url': 'https://example.invalid/source'}
        pins = {'public': pin, 'upstream-only': {**pin, 'redistribute_source': False}}
        response = SimpleNamespace(returncode=0, stdout='{"assets": []}')
        with patch.object(tracker, 'load_pins', return_value=pins), \
             patch.object(tracker.lib, 'gh', return_value=response) as gh, \
             patch.object(tracker.lib, 'log') as log:
            tracker.mirror_command(SimpleNamespace(repository='example/repository', dry_run=True))
        self.assertEqual(gh.call_count, 1)  # The read-only release inventory.
        self.assertEqual([call.args[0] for call in log.call_args_list],
                         ['Would mirror public-' + 'a' * 40 + '.tar.gz'])

    def test_ane_archives_are_explicitly_upstream_only(self):
        pins = json.loads((ROOT / 'sources.json').read_text())
        for name in ('omarchy-ane-tools', 'mil-hwx-compiler'):
            self.assertIs(pins[name]['redistribute_source'], False)

if __name__ == '__main__':
    unittest.main()
