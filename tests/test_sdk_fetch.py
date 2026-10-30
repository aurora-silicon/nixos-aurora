import importlib.util
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.request

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


if __name__ == '__main__':
    unittest.main()
