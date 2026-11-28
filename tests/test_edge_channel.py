"""The NixOS Edge channel ref (aurora-distributions docs/edge-train.md)."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import edgelib  # noqa: E402
import updatelib  # noqa: E402


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


channels = module('edge_cache_channels', 'scripts/cache-channels.py')
follow = module('edge_follow_channel', 'scripts/follow-channel.py')
COMMIT = 'b' * 40
LINUX = {'repository': 'aurora-silicon/linux', 'branch': 'aurora-edge', 'revision': '1' * 40, 'tree': '2' * 40}
MESA = {'repository': 'aurora-silicon/mesa', 'branch': 'aurora-edge', 'revision': '3' * 40, 'tree': '4' * 40}


class GateTests(unittest.TestCase):
    def record(self, commit=COMMIT):
        return {'schema_version': 1, 'release': 'alpha.4', 'pair': {'linux': LINUX, 'mesa': MESA},
                'distributions': {'nixos': {'repository': 'aurora-silicon/nixos-aurora', 'snapshot': commit}}}

    def sources(self, linux='1' * 40, mesa='3' * 40):
        return {'kernel-aurora-edge': {'commit': linux, 'repository': 'https://github.com/aurora-silicon/linux'},
                'mesa-aurora-edge': {'commit': mesa, 'repository': 'https://github.com/aurora-silicon/mesa'}}

    def test_channel_edge_is_a_ref_like_the_others(self):
        self.assertEqual(channels.REFS['edge'], 'channel-edge')
        updatelib.record_channel(updatelib.empty_channels('aurora-silicon/nixos-aurora'), 'edge', {'commit': COMMIT})

    def test_only_the_adopted_train_commit_with_the_train_pair_moves_channel_edge(self):
        edgelib.edge_gate(self.record(), COMMIT, self.sources())
        for record, sources, message in ((self.record('c' * 40), self.sources(), 'adopted Edge train'),
                                         (None, self.sources(), 'adopted Edge train'),
                                         (self.record(), self.sources(mesa='5' * 40), 'pair'),
                                         (self.record(), {}, 'pair')):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                edgelib.edge_gate(record, COMMIT, sources)


class FollowTests(unittest.TestCase):
    def test_an_edge_image_follows_channel_edge(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'flake.nix').write_text(f'{{ inputs.aurora.url = "github:aurora-silicon/nixos-aurora/{COMMIT}"; }}\n')
            (directory / 'flake.lock').write_text(json.dumps({'root': 'root', 'nodes': {
                'root': {'inputs': {'aurora': 'aurora'}},
                'aurora': {'locked': {'type': 'github', 'owner': 'aurora-silicon', 'repo': 'nixos-aurora',
                                      'rev': COMMIT}}}}))
            follow.follow(directory, COMMIT, 'edge')
            self.assertIn('github:aurora-silicon/nixos-aurora/channel-edge', (directory / 'flake.nix').read_text())
            self.assertIn('Aurora edge channel', (directory / 'README').read_text())


class WorkflowTests(unittest.TestCase):
    def test_deploys_and_images_know_edge(self):
        deploy = (ROOT / '.github/workflows/deploy-cache.yml').read_text()
        self.assertIn('advance-edge:', deploy)
        self.assertIn('site/installer/edge-train.json', deploy)
        images = (ROOT / '.github/workflows/images.yml').read_text()
        self.assertIn('options: [testing, stable, edge, pinned]', images)


if __name__ == '__main__':
    unittest.main()
