import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('resolve_cache_inputs', ROOT / 'scripts/resolve-cache-inputs.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublicationPlanTests(unittest.TestCase):
    def setUp(self):
        self.expected = {'kernel': {'outputs': ['kernel-output']}}
        self.head, self.previous = 'a' * 40, 'b' * 40

    def test_module_only_commit_reuses_complete_signed_cache(self):
        plan = module.publication_plan(self.expected, {'kernel-output'}, self.head, self.previous, self.previous, [], ancestor=lambda *_: True)
        self.assertEqual((plan['action'], plan['needed']), ('reuse', []))

    def test_existing_current_release_can_be_deployed_after_publication_was_paused(self):
        plan = module.publication_plan(self.expected, {'kernel-output'}, self.head, self.head, self.previous, [], ancestor=lambda *_: True)
        self.assertEqual(plan['action'], 'deploy')
        plan = module.publication_plan(self.expected, {'kernel-output'}, self.head, self.head, self.head, [], ancestor=lambda *_: True)
        self.assertEqual(plan['action'], 'up-to-date')

    def test_missing_output_cannot_take_the_metadata_reuse_path(self):
        plan = module.publication_plan(self.expected, set(), self.head, self.previous, self.previous, [], ancestor=lambda *_: True)
        self.assertEqual((plan['action'], plan['needed']), ('missing', ['kernel']))

    def test_stale_queued_target_cannot_roll_back_published_or_served_modules(self):
        for published, served in [(self.previous, self.head), (self.head, self.previous)]:
            plan = module.publication_plan(self.expected, {'kernel-output'}, self.head,
                                           published, served, [], ancestor=lambda *_: False)
            self.assertEqual(plan['action'], 'up-to-date')

    def test_explicit_runs_override_empty_automatic_discovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'plan.json'
            args = ['resolve', '--repository', 'aurora-silicon/nixos-aurora', '--previous-metadata', temporary,
                    '--previous-commit', self.previous, '--output', str(output), '--build-runs', '123']
            with patch.object(sys, 'argv', args), \
                 patch.object(module.collector, 'expected_outputs', return_value=self.expected), \
                 patch.object(module.collector, 'store_paths', return_value=set()), \
                 patch.object(module.lib, 'git', return_value=self.head), \
                 patch.object(module.lib, 'is_ancestor', return_value=True), \
                 patch.object(module.lib, 'write_github_output'), \
                 patch.object(module, 'candidate_runs') as search:
                module.main()
            plan = json.loads(output.read_text())
            self.assertEqual((plan['action'], plan['runs']), ('publish', ['123']))
            search.assert_not_called()

    def test_invalid_served_commit_fails_before_evaluating_or_searching(self):
        args = ['resolve', '--repository', 'aurora-silicon/nixos-aurora', '--previous-metadata', 'previous',
                '--previous-commit', self.previous, '--served-commit', 'invalid', '--output', 'unused.json']
        with patch.object(sys, 'argv', args), \
             patch.object(module.collector, 'expected_outputs') as evaluate, \
             patch.object(module, 'candidate_runs') as search, \
             patch('sys.stderr'):
            with self.assertRaises(SystemExit) as error:
                module.main()
        self.assertEqual(error.exception.code, 2)
        evaluate.assert_not_called()
        search.assert_not_called()


if __name__ == '__main__':
    unittest.main()
