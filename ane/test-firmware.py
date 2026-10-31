"""Offline regression: staging a pin cannot make --check claim it is active."""
from pathlib import Path
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
import contextlib
import io
import sys
import tempfile

spec = spec_from_loader('fetch', SourceFileLoader('fetch', sys.argv[1]))
f = module_from_spec(spec)
spec.loader.exec_module(f)
with tempfile.TemporaryDirectory() as work:
    root = Path(work)
    dt = root / 'sys/firmware/devicetree/base'
    dt.mkdir(parents=True)
    (dt / 'compatible').write_bytes(b'apple,t8112\0')
    # No firmware bytes: the test substitutes only verification and checks
    # which paths the installed tool reads and writes.
    f.verify = lambda data, size, sha: None
    _, name, size, sha = f.FETCH['apple,t8112'][:4]
    staged = root / 'var/lib/aurora/ane-firmware' / name
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b'test placeholder')
    assert f.VENDOR == 'run/aurora-firmware/vendorfw'
    with contextlib.redirect_stderr(io.StringIO()):
        assert f.main(['--root', str(root), '--check']) == 1
    active = root / 'run/current-system/firmware' / name
    active.parent.mkdir(parents=True)
    active.write_bytes(b'test placeholder')
    assert f.main(['--root', str(root), '--check']) == 0
    # Detect an earlier vendor image before accepting the store fallback.
    vendor = root / f.VENDOR / name
    vendor.parent.mkdir(parents=True)
    vendor.write_bytes(b'conflicting placeholder')
    def verify(data, size, sha):
        if data.startswith(b'conflicting'):
            raise f.Refuse('wrong pin')
    f.verify = verify
    with contextlib.redirect_stderr(io.StringIO()):
        assert f.main(['--root', str(root), '--check']) == 1
print('NixOS staged, activated, and shadowed firmware checks: PASS')
