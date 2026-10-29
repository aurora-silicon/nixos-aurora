import gzip
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('image_parity', ROOT / 'scripts/check-parity.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
COMMIT = '1' * 40


def cpio(name, content=b'module'):
    filename = name.encode() + b'\0'
    fields = [0, 0o100644, 0, 0, 1, 0, len(content), 0, 0, 0, 0, len(filename), 0]
    header = b'070701' + ''.join(f'{field:08x}' for field in fields).encode() + filename
    return header + b'\0' * (-len(header) % 4) + content + b'\0' * (-len(content) % 4)


class ImageParityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.system = '/nix/store/system'
        self.metadata = {
            'schema': 1, 'mesaCommit': COMMIT, 'kernelCommit': COMMIT, 'audioCommit': COMMIT, 'ucmCommit': COMMIT,
            **{name: '/nix/store/' + name for name in ('kernel', 'mesa', 'alsaUtils', 'audio', 'ucm', 'fexMesa', 'flatpakGL', 'avdFirmware')},
            'defaults': {key: True for key in ('skipLockedControls', 'initrdSequencer', 'malcontentSignal', 'flatpakGL', 'fexMesa')},
        }
        for key, file in (('kernel', 'aurora-source-commit'), ('mesa', '.aurora-mesa-commit'),
                          ('audio', '.aurora-audio-commit'), ('ucm', '.aurora-ucm-commit'),
                          ('fexMesa', '.aurora-mesa-commit'), ('flatpakGL', 'aurora-mesa-commit.25.08'),
                          ('flatpakGL', 'aurora-mesa-commit.26.08')):
            self.write(self.metadata[key] + '/' + file, COMMIT + '\n')
        for arch in ('lib64', 'lib'):
            self.write(f'/nix/store/fexMesa/usr/{arch}/libvulkan_asahi.so', b'ELF')
        self.write('/nix/store/alsaUtils/bin/alsactl', b'ELF')
        for branch in ('25.08', '26.08'):
            self.write('/nix/store/flatpakGL/refs/heads/runtime/org.freedesktop.Platform.GL.aurora/aarch64/' + branch, 'ostree-commit')
        for variant in ('v2-t0', 'v3-t0', 'v3-t1', 'v4-t0', 'v5-t0', 'v5-t1'):
            self.write(f'/nix/store/avdFirmware/lib/firmware/apple/avd-fw-{variant}.bin', b'firmware')
        self.write(self.system + '/initrd', cpio('lib/modules/kernel/snd-seq.ko.zst') + cpio('TRAILER!!!', b''))
        self.save_metadata()

    def write(self, path, data):
        p = self.root / path.lstrip('/')
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
        return p

    def save_metadata(self):
        self.write(self.system + '/etc/aurora/parity.json', json.dumps(self.metadata))

    def check(self):
        module.check(module.basics.Root(self.root, self.system))

    def test_complete_root_and_compressed_initrd_are_accepted(self):
        self.check()
        data = (self.root / self.system.lstrip('/') / 'initrd').read_bytes()
        self.write(self.system + '/initrd', gzip.compress(data, mtime=0))
        self.check()

    def test_image_with_stale_graphics_is_rejected(self):
        self.write('/nix/store/fexMesa/.aurora-mesa-commit', '2' * 40)
        with self.assertRaisesRegex(ValueError, 'stale image payload'):
            self.check()

    def test_the_patched_alsa_utility_must_be_installed(self):
        (self.root / 'nix/store/alsaUtils/bin/alsactl').unlink()
        with self.assertRaisesRegex(ValueError, 'patched ALSA utilities are missing'):
            self.check()

    def test_an_outer_stamp_cannot_replace_an_absent_runtime(self):
        (self.root / 'nix/store/flatpakGL/refs/heads/runtime/org.freedesktop.Platform.GL.aurora/aarch64/26.08').unlink()
        with self.assertRaisesRegex(ValueError, '26.08 is missing'):
            self.check()

    def test_the_sequencer_must_be_in_the_actual_initrd(self):
        self.write(self.system + '/initrd', cpio('lib/modules/kernel/snd-pcm.ko') + cpio('TRAILER!!!', b''))
        with self.assertRaisesRegex(ValueError, 'does not carry snd-seq'):
            self.check()

    def test_missing_or_disabled_defaults_are_rejected(self):
        for change in ('missing', 'disabled'):
            with self.subTest(change=change):
                self.metadata['defaults']['flatpakGL'] = False
                if change == 'missing':
                    del self.metadata['defaults']['flatpakGL']
                self.save_metadata()
                with self.assertRaisesRegex(ValueError, 'every Aurora parity default'):
                    self.check()

    def test_truncated_cpio_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'truncated initrd'):
            list(module.cpio_names(io.BytesIO(cpio('module')[:-2])))


if __name__ == '__main__':
    unittest.main()
