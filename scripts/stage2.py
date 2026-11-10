"""The shared Aura + device trees + gzip U-Boot + m1n1 options format."""
import re
import struct
import zlib

DTB_MAGIC = b'\xd0\x0d\xfe\xed'
OPTION = re.compile(rb'(chosen\.[A-Za-z0-9_.,-]+=[ -~]*|display=[ -~]*|mitigations=[ -~]*)')
MAX_BYTES = 64 * 1024 * 1024


def root_compatible(blob):
    if len(blob) < 40:
        raise ValueError('short device tree')
    fields = struct.unpack_from('>10I', blob)
    magic, total, struct_offset, strings_offset = fields[:4]
    strings_size, struct_size = fields[8], fields[9]
    if (magic != 0xD00DFEED or total != len(blob)
            or struct_offset < 40 or strings_offset < 40
            or struct_offset + struct_size > total or strings_offset + strings_size > total):
        raise ValueError('invalid device tree header')
    strings = blob[strings_offset:strings_offset + strings_size]
    cursor, end = struct_offset, struct_offset + struct_size
    if cursor + 4 > end or struct.unpack_from('>I', blob, cursor)[0] != 1:
        raise ValueError('device tree has no root node')
    cursor += 4
    name_end = blob.find(b'\0', cursor, end)
    if name_end < 0 or blob[cursor:name_end]:
        raise ValueError('invalid device tree root name')
    cursor = (name_end + 4) & ~3
    while cursor + 4 <= end:
        token = struct.unpack_from('>I', blob, cursor)[0]
        cursor += 4
        if token == 4:
            continue
        if token != 3 or cursor + 8 > end:
            break
        size, name_offset = struct.unpack_from('>II', blob, cursor)
        cursor += 8
        name_end = strings.find(b'\0', name_offset)
        if name_offset >= len(strings) or name_end < 0 or cursor + size > end:
            raise ValueError('invalid device tree property')
        name = strings[name_offset:name_end]
        value = blob[cursor:cursor + size]
        cursor = (cursor + size + 3) & ~3
        if name == b'compatible':
            if not value or not value.endswith(b'\0'):
                raise ValueError('invalid device tree compatible')
            try:
                return value.split(b'\0', 1)[0].decode('ascii')
            except UnicodeDecodeError as error:
                raise ValueError('invalid device tree compatible') from error
    raise ValueError('device tree root has no compatible')


def parse(image, aura):
    """Return device trees and the intact next-stage trailer after validation."""
    if not 0 < len(image) <= MAX_BYTES:
        raise ValueError('Stage 2 size is out of range')
    if not aura or not image.startswith(aura):
        raise ValueError('Stage 2 does not start with the aura build')
    cursor = len(aura)
    trees = []
    while image[cursor:cursor + 4] == DTB_MAGIC:
        if cursor + 40 > len(image):
            raise ValueError('truncated device tree')
        length = struct.unpack_from('>I', image, cursor + 4)[0]
        if length < 40 or cursor + length > len(image):
            raise ValueError('invalid device tree length')
        blob = image[cursor:cursor + length]
        trees.append((root_compatible(blob), blob))
        cursor += length
    if not trees:
        raise ValueError('Stage 2 carries no device trees')
    trailer = image[cursor:]
    if not trailer.startswith(b'\x1f\x8b\x08'):
        raise ValueError('U-Boot is not one gzip member after the device trees')
    inflater = zlib.decompressobj(wbits=31)
    try:
        uboot = inflater.decompress(trailer, MAX_BYTES + 1)
    except zlib.error as error:
        raise ValueError('U-Boot does not decompress') from error
    if len(uboot) > MAX_BYTES:
        raise ValueError('Uncompressed U-Boot size is out of range')
    if not inflater.eof or not uboot:
        raise ValueError('U-Boot does not decompress')
    options = [line for line in inflater.unused_data.split(b'\n') if line]
    if any(not OPTION.fullmatch(line) for line in options):
        raise ValueError('unexpected data after U-Boot')
    return {
        'trees': trees,
        'trailer': trailer,
        'ubootBytes': len(uboot),
        'options': [line.decode('ascii') for line in options],
    }
