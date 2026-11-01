"""Validate the firmware's raw reset vectors against its linked ARM images."""
from pathlib import Path
import hashlib
import struct
import sys

root = Path(sys.argv[1])
# clang 22, upstream Make and Meson defaults must produce these exact images.
expected = [
    ('v2-t0', 0xc000, '0db99c023d91e89e866d763229912e373cb0cfd5b91f46603df9d926ce036967'),
    ('v3-t0', 0x10000, 'fc5219b2166e114fcd88898a8b2fb93fadfa8406dfb2c63c4d48c1b75adb49a9'),
    ('v3-t1', 0x10000, '6d7f74406e93b9e0b6b6cf7bd630b5669a2e8b43a143d6abaaa85c1f93b02e34'),
    ('v3-t2', 0x10000, '7bc2f5a30543331be6050ed2bb68198139e905b42c4622724b50cf8bf59e531a'),
    ('v4-t0', 0x12000, 'adedf50ff0cb7ad8db539126585afab1d2fd83a82cd3ed2d3f7e0ec6d06723e2'),
    ('v5-t0', 0x10000, 'aaa50276a9cc2320cb0ee6633319e82a54cf339018c03e22f33961a336bc61d1'),
    ('v5-t1', 0x12000, '6490420bc7c0156686aface9057815849a4e4a823a0bef7a82f9274144c03343'),
    ('v5-t2', 0x12000, '585f0a54c47078cb1c8c5928d7937dbcb99391aab53cec8f712af30c15071d5f'),
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
