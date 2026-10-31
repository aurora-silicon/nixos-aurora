import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('ci_plan', Path(__file__).resolve().parents[1]/'scripts/ci-plan.py')
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


class PlanTests(unittest.TestCase):
    def test_fingerprint_update_does_not_rebuild_unchanged_kernel(self):
        self.assertEqual(plan.select({'kernel': '/nix/store/same-kernel.drv', 'libfprint': '/nix/store/new-reader.drv'},
                                     {'kernel': '/nix/store/same-kernel.drv', 'libfprint': '/nix/store/old-reader.drv'}), ['libfprint'])

    def test_new_outputs_build_and_removed_outputs_do_not(self):
        self.assertEqual(plan.select({'kernel': 'unchanged', 'sep': 'new'}, {'kernel': 'unchanged', 'retired': 'old'}), ['sep'])

    def test_explicit_validation_can_rebuild_unchanged_output(self):
        self.assertEqual(plan.select({'kernel': 'same'}, {'kernel': 'same'}, ['kernel', 'kernel']), ['kernel'])
        with self.assertRaises(ValueError):
            plan.select({'kernel': 'same'}, requested=['unknown'])

    def test_selection_without_a_baseline_checks_entire_set(self):
        self.assertEqual(plan.select({'sep': 's', 'kernel': 'k'}), ['kernel', 'sep'])

    def test_generation_proof_changes_rebuild_graphics_with_identical_derivations(self):
        outputs = {'mesa': 'same-mesa', 'graphics': 'same-graphics'}
        self.assertEqual(plan.select(outputs, outputs,
                                     changed_paths=['scripts/test-graphics-generation']), ['graphics'])
