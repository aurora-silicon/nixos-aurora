import importlib.util
from contextlib import nullcontext
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('sdk_fetch',
    Path(__file__).resolve().parents[1] / 'flatpak-gl/fetch-sdk.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SdkTransportTests(unittest.TestCase):
    def test_listener_serves_only_public_repository_objects(self):
        requested = []
        def download(path, destination, ca):
            requested.append(path)
            destination.write_bytes(b'unchanged object bytes')
            return 200
        object_path = '/objects/11/' + '2' * 62 + '.commit'
        with module.object_server(None, download) as url:
            self.assertEqual(urllib.request.urlopen(url + object_path).read(), b'unchanged object bytes')
            for bad in ('/../../etc/passwd', '/objects/11/' + '2' * 62 + '.commit?other=1',
                        '/https://other.example/private', '/refs/heads/unpinned'):
                with self.subTest(path=bad), self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(url + bad)
                self.assertEqual(error.exception.code, 404)
                error.exception.close()
        self.assertEqual(requested, [object_path])

    def test_missing_objects_remain_missing(self):
        with module.object_server(None, lambda *_args: 404) as url:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(url + '/objects/11/' + '2' * 62 + '.commitmeta')
            self.assertEqual(error.exception.code, 404)
            error.exception.close()

    def test_unpinned_or_unrelated_refs_are_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            for refs in ({}, {'unrelated': '1' * 64},
                         {'runtime/org.freedesktop.Sdk/aarch64/25.08': 'short'}):
                with self.subTest(refs=refs), self.assertRaises(ValueError):
                    module.fetch_sdk(temporary, refs, None)

    def test_runtime_refs_follow_the_supplied_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / 'runtimes.json'
            refs = {'runtime/org.freedesktop.Sdk/aarch64/27.08': '1' * 64}
            lock.write_text(json.dumps({'27.08': {'refs': refs}}))
            with patch.object(module, 'object_server', return_value=nullcontext('http://fixture')), \
                    patch.object(module.subprocess, 'run') as run:
                module.fetch_sdk(temporary, refs, None, sdk_lock=lock)
            self.assertIn(['ostree', f'--repo={temporary}', 'pull', '--depth=0', 'source', '1' * 64],
                          [call.args[0] for call in run.call_args_list])

    def test_standalone_script_accepts_an_explicit_lock_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'fetch.py'
            shutil.copyfile(module.__file__, script)
            refs, lock = root / 'refs.json', root / 'lock.json'
            refs.write_text('{}')
            lock.write_text('{}')
            result = subprocess.run([sys.executable, str(script), '--repo', temporary,
                                     '--refs', str(refs), '--ca-file', 'unused', '--sdk-lock', str(lock)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Expected pinned Freedesktop SDK refs', result.stderr)


if __name__ == '__main__':
    unittest.main()
