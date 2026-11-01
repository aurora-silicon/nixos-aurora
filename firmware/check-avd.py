"""Validate the firmware's raw reset vectors against its linked ARM images."""
from pathlib import Path
import hashlib
import struct
import sys

root = Path(sys.argv[1])
# clang 22, upstream Make and Meson defaults must produce these exact images.
expected = [
    ('v2-t0', 0xc000, '2f6e5cc57c25e1a80720e514326e10a25c4afc013670aacce89d9a9dd3439aef'),
    ('v3-t0', 0x10000, '5d26b2d170de7782f05268207e7fcb73eef3a4d240b5a4fd4f0a76d0b60fe12b'),
    ('v3-t1', 0x10000, 'f49ebf15cdccdd9d76b15695157fe27dfef93087d406639de0e126fef81300bd'),
    ('v4-t0', 0x12000, 'af6f7034ef40c897b22e8285138c839b0a568270c0fbb9521a43eb37e8a3020e'),
    ('v5-t0', 0x10000, '96f2189d39d751266c12401345daca333055da48f76293e4dcdbdbd705cd2d1a'),
    ('v5-t1', 0x12000, 'f5d516f3ce1ca8ebe850cf0428fff07e487662e7f7981b2991a0070449d82479'),
    ('v5-t2', 0x12000, '931f33bb99e68c7d8fccb2bbe976ddd9914f7235a98851d9ab8a9a1ba515526d'),
]
for name, size, expected_hash in expected:
    files = list(root.rglob('avd-fw-' + name + '.bin'))
    assert len(files) == 1 and files[0].stat().st_size == size, name
    firmware = files[0].read_bytes()
    actual_hash = hashlib.sha256(firmware).hexdigest()
    print(f"{actual_hash}  {files[0].name}", flush=True)
    if actual_hash != expected_hash:
        raise SystemExit(f"{name}: expected {expected_hash}, got {actual_hash}; check the clang toolchain")
    elf = (root / ('avd-fw-' + name + '.elf')).read_bytes()
    assert elf[:6] == b'\x7fELF\x01\x01' and struct.unpack_from('<H', elf, 18)[0] == 40
    stack, reset = struct.unpack_from('<II', firmware)
    entry = struct.unpack_from('<I', elf, 24)[0]
    assert stack and stack % 8 == 0 and reset & 1 and reset == entry, name
    assert 0 < (reset & ~1) < size, name
