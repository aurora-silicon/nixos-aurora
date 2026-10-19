"""Validate the firmware's raw reset vectors against its linked ARM images."""
from pathlib import Path
import struct
import sys

root = Path(sys.argv[1])
for name, size in [('v2-t0', 0xc000), ('v3-t0', 0x10000), ('v3-t1', 0x10000),
                   ('v4-t0', 0x12000), ('v5-t0', 0x10000), ('v5-t1', 0x12000)]:
    files = list(root.rglob('avd-fw-' + name + '.bin'))
    assert len(files) == 1 and files[0].stat().st_size == size, name
    firmware = files[0].read_bytes()
    elf = (root / ('avd-fw-' + name + '.elf')).read_bytes()
    assert elf[:6] == b'\x7fELF\x01\x01' and struct.unpack_from('<H', elf, 18)[0] == 40
    stack, reset = struct.unpack_from('<II', firmware)
    entry = struct.unpack_from('<I', elf, 24)[0]
    assert stack and stack % 8 == 0 and reset & 1 and reset == entry, name
    assert 0 < (reset & ~1) < size, name
