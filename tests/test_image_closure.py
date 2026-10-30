import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('image_closure',
    Path(__file__).resolve().parents[1] / 'scripts/verify-image-closure.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

COMMIT = '1' * 40
CANDIDATE = '/nix/store/' + '1' * 32 + '-candidate'
OTHER = '/nix/store/' + '2' * 32 + '-other'
HASH = 'sha256-' + 'A' * 43 + '='
CHANGED = 'sha256-' + 'B' * 43 + '='


class ImageClosureTests(unittest.TestCase):
    def setUp(self):
        self.proof = {'schema': 1, 'commit': COMMIT, 'narHashes': {CANDIDATE: HASH}}
        self.actual = {CANDIDATE: {'narHash': HASH}, OTHER: {'narHash': HASH}}

    def test_only_exact_authenticated_hashes_leave_the_ordinary_trust_check(self):
        with mock.patch.object(module.subprocess, 'check_output', return_value=json.dumps(self.actual)), \
                mock.patch.object(module.subprocess, 'run') as run:
            module.verify(['system'], self.proof, COMMIT)
        self.assertEqual(run.call_args_list, [
            mock.call(['nix', 'store', 'verify', '--recursive', '--no-trust', 'system'], check=True),
            mock.call(['nix', 'store', 'verify', OTHER], check=True),
        ])

    def test_changed_candidate_hash_is_rejected_before_trust_exemptions(self):
        self.actual[CANDIDATE]['narHash'] = CHANGED
        with mock.patch.object(module.subprocess, 'check_output', return_value=json.dumps(self.actual)), \
                mock.patch.object(module.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'no longer matches'):
                module.verify(['system'], self.proof, COMMIT)
        run.assert_not_called()

    def test_unaccounted_unsigned_paths_cannot_bypass_nix_trust(self):
        def check(command, **_kwargs):
            if OTHER in command:
                raise subprocess.CalledProcessError(2, command)
        with mock.patch.object(module.subprocess, 'check_output', return_value=json.dumps(self.actual)), \
                mock.patch.object(module.subprocess, 'run', side_effect=check):
            with self.assertRaises(subprocess.CalledProcessError):
                module.verify(['system'], self.proof, COMMIT)

    def test_contents_are_checked_even_for_authenticated_paths(self):
        with mock.patch.object(module.subprocess, 'check_output', return_value=json.dumps(self.actual)), \
                mock.patch.object(module.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'verify')):
            with self.assertRaises(subprocess.CalledProcessError):
                module.verify(['system'], self.proof, COMMIT)

    def test_old_or_incomplete_proofs_are_rejected(self):
        for proof in ({**self.proof, 'commit': '2' * 40},
                      {'schema': 1, 'commit': COMMIT}, {**self.proof, 'schema': 2}):
            with self.subTest(proof=proof), self.assertRaises(ValueError):
                module.ordinary_paths(proof, COMMIT, module.nar_hashes(self.actual))

    def test_malformed_closure_metadata_is_rejected(self):
        for info in ({}, {OTHER: {'narHash': 'missing'}}, {'/etc/passwd': {'narHash': HASH}}):
            with self.subTest(info=info), self.assertRaises(ValueError):
                module.nar_hashes(info)


if __name__ == '__main__':
    unittest.main()
