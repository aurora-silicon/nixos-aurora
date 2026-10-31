"""Demo package boundaries: no hardware, recording, playback or network required."""
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'demos'
loader = importlib.machinery.SourceFileLoader('model_fetch', str(DATA / 'aurora-model-fetch'))
spec = importlib.util.spec_from_loader(loader.name, loader)
fetch = importlib.util.module_from_spec(spec)
loader.exec_module(fetch)


class ModelFetchTests(unittest.TestCase):
    def fixture(self, root):
        data = root / 'data'
        data.mkdir()
        content = b'audited weights'
        (data / 'models.json').write_text(json.dumps({'example': {
            'url': 'https://example.invalid/immutable/model',
            'sha256': hashlib.sha256(content).hexdigest(),
            'filename': 'model.bin', 'license': 'MIT', 'max_bytes': 100}}))
        return data, content

    def test_verified_download_is_atomic_and_reused_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data, content = self.fixture(root)
            with patch.object(fetch, 'DATA', data), patch.object(fetch.urllib.request, 'urlopen', return_value=io.BytesIO(content)) as network:
                result = fetch.ensure('example', root / 'cache')
                self.assertEqual(result.read_bytes(), content)
                self.assertEqual(fetch.ensure('example', root / 'cache'), result)
                self.assertEqual(network.call_count, 1)
                self.assertEqual(result.stat().st_mode & 0o777, 0o600)
                self.assertFalse(list(result.parent.glob('.fetch-*')))

    def test_bad_download_or_oversize_never_replaces_existing_weights(self):
        for content in (b'changed', b'x' * 101):
            with self.subTest(content=content[:10]), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                data, original = self.fixture(root)
                target = root / 'cache/example/model.bin'
                target.parent.mkdir(parents=True)
                target.write_bytes(original)
                with patch.object(fetch, 'DATA', data), patch.object(fetch.urllib.request, 'urlopen', return_value=io.BytesIO(content)):
                    with self.assertRaises(ValueError):
                        fetch.ensure('example', root / 'cache', refresh=True)
                self.assertEqual(target.read_bytes(), original)
                self.assertFalse(list(target.parent.glob('.fetch-*')))

    def test_corrupt_cache_is_rejected_before_network_or_use(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data, _ = self.fixture(root)
            target = root / 'cache/example/model.bin'
            target.parent.mkdir(parents=True)
            target.write_bytes(b'corrupt')
            with patch.object(fetch, 'DATA', data), patch.object(fetch.urllib.request, 'urlopen') as network:
                with self.assertRaisesRegex(ValueError, 'cached SHA-256 mismatch'):
                    fetch.ensure('example', root / 'cache')
                network.assert_not_called()
            self.assertEqual(target.read_bytes(), b'corrupt')


class EnginePolicyTests(unittest.TestCase):
    def run_wrapper(self, engine, info, extra=(), bundle=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cli = root / 'cli'
            cli.write_text(f'#!{sys.executable}\nimport json,os,sys\nprint(json.dumps({{"args":sys.argv[1:],"bundle":os.environ.get("WHISPER_ANE_ENCODER")}}))\n')
            vulkan = root / 'vulkaninfo'
            vulkan.write_text(f'#!{sys.executable}\nprint({info!r})\n')
            for exe in (cli, vulkan):
                exe.chmod(0o755)
            wrapper = root / 'wrapper'
            wrapper.write_text((DATA / 'whisper.cpp-aurora').read_text().replace('@CLI@', str(cli)).replace('@VULKANINFO@', str(vulkan)))
            env = dict(os.environ)
            env.pop('WHISPER_ANE_ENCODER', None)
            if bundle:
                (root / 'open/package').mkdir(parents=True)
                (root / 'open/package/manifest.json').write_text('{}')
                env['WHISPER_ANE_ENCODER'] = str(root / 'open')
            return subprocess.run([sys.executable, str(wrapper), '--engine', engine,
                                   '-m', 'explicit-model.bin', '-f', 'file.wav', *extra],
                                  text=True, capture_output=True, env=env)

    def test_auto_uses_cpu_when_only_cpu_vulkan_exists(self):
        result = self.run_wrapper('auto', 'PHYSICAL_DEVICE_TYPE_CPU')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('engine=cpu', result.stderr)
        self.assertIn('--no-gpu', json.loads(result.stdout)['args'])

    def test_auto_uses_hardware_vulkan(self):
        result = self.run_wrapper('auto', 'PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('engine=gpu', result.stderr)
        self.assertNotIn('--no-gpu', json.loads(result.stdout)['args'])

    def test_explicit_cpu_overrides_a_bundle(self):
        result = self.run_wrapper('cpu', 'PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU', bundle=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(json.loads(result.stdout)['bundle'])
        self.assertIn('engine=cpu', result.stderr)

    def test_forced_gpu_and_ane_refuse_missing_backend(self):
        for engine in ('gpu', 'ane'):
            with self.subTest(engine=engine):
                result = self.run_wrapper(engine, 'PHYSICAL_DEVICE_TYPE_CPU')
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(result.stdout)


class FetchFailureBoundaryTests(unittest.TestCase):
    def test_failed_model_fetch_never_starts_a_consumer(self):
        for name in ('aurora-capture-ns', 'whisper.cpp-aurora'):
            with self.subTest(consumer=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                marker = root / 'consumer-started'
                fetcher = root / 'fetch'
                fetcher.write_text(f'#!{sys.executable}\nimport sys\nsys.exit(7)\n')
                fetcher.chmod(0o755)
                consumer = root / 'consumer'
                consumer.write_text(f'#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n')
                consumer.chmod(0o755)
                wrapper = root / 'wrapper'
                text = (DATA / name).read_text().replace('@FETCH@', str(fetcher))
                text = text.replace('@CLI@', str(consumer)).replace('@LAUNCHER@', str(consumer))
                wrapper.write_text(text)
                args = ['--engine', 'cpu']
                args += ['--source', 'alsa_input.example', '--model', 'rnnoise'] if name == 'aurora-capture-ns' else ['-f', 'file.wav']
                result = subprocess.run([sys.executable, str(wrapper), *args], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('model fetch failed', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertFalse(marker.exists())

if __name__ == '__main__':
    unittest.main()
