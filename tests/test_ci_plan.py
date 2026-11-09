import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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
        self.assertEqual(plan.select(outputs, outputs, changed_paths=['scripts/testlib.sh']), ['graphics'])

    def test_manual_dispatch_with_empty_package_input_builds_every_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            event = Path(temporary) / 'event.json'
            event.write_text(json.dumps({'inputs': {'packages': ''}}))
            env = {'GITHUB_EVENT_PATH': str(event), 'GITHUB_SHA': 'a' * 40,
                   'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/main'}
            output = io.StringIO()
            with patch.dict(os.environ, env), \
                 patch.object(plan, 'derivations', return_value={'kernel': 'same', 'mesa': 'same'}) as evaluate, \
                 patch.object(plan.subprocess, 'check_output') as git, \
                 patch('sys.stdout', output):
                plan.main()
            self.assertEqual(json.loads(output.getvalue().removeprefix('packages=')), ['kernel', 'mesa'])
            evaluate.assert_called_once_with('a' * 40)
            git.assert_not_called()


class GitEventPlanTests(unittest.TestCase):
    def setUp(self):
        from contextlib import chdir
        import subprocess
        self.subprocess = subprocess
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.enterContext(patch.dict(os.environ, {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'}))
        self.git('init', '-q', '-b', 'main')
        (self.repo / 'kernel.txt').write_text('old kernel\n')
        self.base = self.commit('base')
        self.enterContext(chdir(self.repo))

    def git(self, *args):
        return self.subprocess.check_output([
            'git', '-C', str(self.repo), '-c', 'user.name=CI fixture',
            '-c', 'user.email=ci@example.invalid', '-c', 'commit.gpgsign=false', *args,
        ], text=True, stderr=self.subprocess.PIPE).strip()

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD')

    def run_main(self, event_name, head, before, outputs):
        event = self.root / 'event.json'
        event.write_text(json.dumps({'before': before}))
        env = {'GITHUB_EVENT_PATH': str(event), 'GITHUB_SHA': head, 'GITHUB_EVENT_NAME': event_name,
               'GITHUB_REF': 'refs/pull/1/merge' if event_name == 'pull_request' else 'refs/heads/main'}
        output = io.StringIO()
        with patch.dict(os.environ, env), \
             patch.object(plan, 'derivations', side_effect=lambda commit: outputs[commit]) as evaluate, \
             patch('sys.stdout', output):
            plan.main()
        return json.loads(output.getvalue().removeprefix('packages=')), [call.args[0] for call in evaluate.call_args_list]

    def test_push_compares_event_before_even_when_origin_main_already_points_at_head(self):
        (self.repo / 'kernel.txt').write_text('new kernel\n')
        head = self.commit('kernel update')
        self.git('update-ref', 'refs/remotes/origin/main', head)
        selected, evaluated = self.run_main('push', head, self.base, {
            self.base: {'kernel': 'old-kernel', 'mesa': 'same-mesa'},
            head: {'kernel': 'new-kernel', 'mesa': 'same-mesa'},
        })
        self.assertEqual(selected, ['kernel'])
        self.assertEqual(evaluated, [head, self.base])

    def test_pr_merge_compares_with_current_main_and_ignores_the_event_before_field(self):
        self.git('switch', '-qc', 'proposal')
        (self.repo / 'kernel.txt').write_text('proposed kernel\n')
        self.commit('proposed kernel')
        self.git('switch', '-q', 'main')
        (self.repo / 'unrelated-docs.txt').write_text('main advanced\n')
        main = self.commit('unrelated main update')
        self.git('update-ref', 'refs/remotes/origin/main', main)
        self.git('merge', '-q', '--no-ff', '--no-edit', 'proposal')
        head = self.git('rev-parse', 'HEAD')
        selected, evaluated = self.run_main('pull_request', head, 'f' * 40, {
            main: {'kernel': 'old-kernel', 'mesa': 'same-mesa'},
            head: {'kernel': 'proposed-kernel', 'mesa': 'same-mesa'},
        })
        self.assertEqual(selected, ['kernel'])
        self.assertEqual(evaluated, [head, main])
