"""The calibration helper, on synthetic boot containers and records only."""
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch


PACKAGE = Path(__file__).resolve().parents[1] / 'sep'


def load(name, module):
    loader = importlib.machinery.SourceFileLoader(module, str(PACKAGE / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    loaded = importlib.util.module_from_spec(spec)
    loader.exec_module(loaded)
    return loaded


helper = load('prepare-sep-calibration', 'prepare_sep_calibration')
calibration_ready = load('calibration-ready', 'calibration_ready')


# ---------------------------------------------------------------- DER records

def der(tag, value):
    if len(value) < 0x80:
        return bytes([tag, len(value)]) + value
    count = (len(value).bit_length() + 7) // 8
    return bytes([tag, 0x80 | count]) + len(value).to_bytes(count, 'big') + value


def text(value):
    return der(0x16, value)


def private(name, value):
    """[PRIVATE NAME] SEQUENCE { IA5String NAME, value }, as IM4M writes it."""
    number = int.from_bytes(name, 'big')
    identifier = [number & 0x7f]
    number >>= 7
    while number:
        identifier.insert(0, 0x80 | number & 0x7f)
        number >>= 7
    body = der(0x30, text(name) + value)
    return bytes([0xff] + identifier) + der(0, body)[1:]


def im4m(objects):
    """An IM4M whose MANB holds `objects`: {name: {property: value element}}."""
    body = b''.join(private(name, der(0x31, b''.join(private(key, value)
                                                      for key, value in props.items())))
                    for name, props in objects.items())
    manb = private(b'MANB', der(0x31, body))
    return der(0x30, text(b'IM4M') + der(0x02, b'\x00') + der(0x31, manb)
               + der(0x04, b'signature') + der(0x30, der(0x30, b'')))


def octets(value):
    return der(0x04, value)


def integer(value):
    return der(0x02, value.to_bytes((value.bit_length() + 8) // 8, 'big'))


def im4p(payload, kind=b'FSC2'):
    return der(0x30, text(b'IM4P') + text(kind) + text(b'1.0') + der(0x04, payload))


def img4(payload_element, manifest):
    return der(0x30, text(b'IMG4') + payload_element + der(0xa0, manifest))


def comb(image, trust):
    return der(0x30, text(b'comb')
               + der(0x30, text(b'fdrd') + der(0x04, image))
               + der(0x30, text(b'secb') + der(0x04, trust)))


CHIP, ECID, SERIAL = 0x8132, 0x0011223344556677, b'TESTSERIAL1'
OTHER_ECID = 0x0011223344556678
SENSOR = '00003356-0123456789ABCDEF0123456789ABCDEF'
CALIBRATION = im4p(b'CALB' + bytes(300))
OTHER = im4p(b'CALB' + bytes(299) + b'\x01')
FACTORY = img4(CALIBRATION, im4m({b'MANP': {b'srvn': octets(b'\x01')},
                                  b'FSC2': {b'DGST': octets(hashlib.sha384(CALIBRATION).digest())}}))
TRUST = b'trust bundle ' + bytes(64)
OLD_TRUST = b'old trust bundle ' + bytes(64)


def seal(payload=CALIBRATION, serial=SERIAL, extra=None):
    objects = {b'MANP': {b'SrNm': octets(serial), b'BORD': integer(0x26)},
               b'FSC2': {b'DGST': octets(hashlib.sha384(payload).digest()),
                         b'clas': octets(b'\x00' * 4)},
               b'MSRk': {b'DGST': octets(bytes(48))}}
    for name, props in (extra or {}).items():
        objects.setdefault(name, {}).update(props)
    return im4m(objects)


def sealed(payload=CALIBRATION, manifest=None, trust=TRUST):
    return comb(img4(payload, manifest or seal(payload)), trust)


def records(**changes):
    out = {
        f'FSC2-{SENSOR}': FACTORY,
        f'MSRk-{SENSOR}': b'root key',
        f'seal-{CHIP:08X}-{ECID:016X}': seal(),
        f'trustobject-{hashlib.sha256(TRUST).hexdigest().upper()}': TRUST,
        f'trustobject-{hashlib.sha256(OLD_TRUST).hexdigest().upper()}': OLD_TRUST,
        'trustobject-current': TRUST,
    }
    for name, value in changes.items():
        name = name.replace('_', '-')
        if value is None:
            out.pop(name, None)
        else:
            out[name] = value
    return out


IDENTITY = (CHIP, ECID, SERIAL)
# FSCl comb records as carved: a full one, and the looser layout the extractor
# accepts (a secb holding only its name, manifest markers after the IM4P).
FSCL_RECORDS = [
    comb(img4(im4p(b'CALB' + bytes(40), b'FSCl'), im4m({b'MANP': {}})), TRUST),
    der(0x30, text(b'comb')
        + der(0x30, text(b'fdrd') + der(0x04, der(0x30, text(b'IMG4') + im4p(b'CALB' + bytes(40), b'FSCl')
                                                + text(b'IM4M') + text(b'FSCl'))))
        + der(0x30, text(b'secb'))),
]
EXPECTED = sealed()


# ---------------------------------------------------------------- APFS images

BS = 4096


def checksummed(block):
    block = bytearray(block.ljust(BS, b'\0'))
    struct.pack_into('<Q', block, 0, helper.fletcher64(bytes(block)))
    return bytes(block)


def obj(oid, xid, kind, body):
    return struct.pack('<QQQII', 0, oid, xid, kind, 0) + body


def node(entries, fixed, root=True, leaf=True, oid=0, xid=1):
    """A B-tree node holding (key, value) entries."""
    width = 4 if fixed else 8
    toc, keys, values = b'', b'', b''
    for key, value in entries:
        values = value + values
        if fixed:
            toc += struct.pack('<HH', len(keys), len(values))
        else:
            toc += struct.pack('<HHHH', len(keys), len(key), len(values), len(value))
        keys += key
    flags = (1 if root else 0) | (2 if leaf else 0) | (4 if fixed else 0)
    header = struct.pack('<HHI', flags, 0 if leaf else 1, len(entries)) + \
        struct.pack('<HHHHHHHH', 0, len(toc), 0, 0, 0, 0, 0, 0)
    body = obj(oid, xid, 0x40000002 if root else 0x40000003, header + toc + keys)
    end = BS - (40 if root else 0)
    assert len(body) + len(values) <= end
    return checksummed(body + bytes(end - len(body) - len(values)) + values + bytes(BS - end))


def fs_key(oid, kind, rest=b''):
    return struct.pack('<Q', oid | kind << 60) + rest


def apfs(files, *, role=helper.APFS_ROLE_HARDWARE, flags=1, bsd_flags=0, path=None,
         hashed=True, extra_volume=True, newer=None):
    """A container whose Hardware volume holds `files` in its factory cache.
    `newer` maps to a second, newer checkpoint superblock pointing at another
    container built from those files."""
    blocks = {}
    path = helper.APFS_FACTORY if path is None else path
    entries, next_block, next_oid = [], 20, 16
    entries.append((fs_key(2, 3), inode(2, 0)))
    parent = 2
    for part in path:
        oid, next_oid = next_oid, next_oid + 1
        entries.append((drec_key(parent, part.encode(), hashed), drec(oid, 4)))
        entries.append((fs_key(oid, 3), inode(oid, 0)))
        parent = oid
    for name, data in files.items():
        oid, next_oid = next_oid, next_oid + 1
        entries.append((drec_key(parent, name.encode(), hashed), drec(oid, 8)))
        entries.append((fs_key(oid, 3), inode(oid, len(data), bsd_flags)))
        if data:
            count = (len(data) + BS - 1) // BS
            for index in range(count):
                blocks[next_block + index] = data[index * BS:(index + 1) * BS].ljust(BS, b'\0')
            entries.append((fs_key(oid, 8, struct.pack('<Q', 0)),
                            struct.pack('<QQQ', count * BS, next_block, 0)))
            next_block += count
    entries.sort(key=lambda e: e[0])
    blocks[10] = node(entries, False, oid=1027)
    blocks[9] = node([(struct.pack('<QQ', 1027, 1), struct.pack('<IIQ', 0, BS, 10))], True, oid=9)
    blocks[8] = checksummed(obj(8, 1, 0x4000000b, struct.pack('<IIIIQ', 0, 0, 0, 0, 9)))
    volume = bytearray(1024)
    volume[0:4] = b'APSB'
    struct.pack_into('<Q', volume, 56 - 32, 1 if hashed else 0)
    struct.pack_into('<I', volume, 116 - 32, 2)
    struct.pack_into('<QQ', volume, 128 - 32, 8, 1027)
    struct.pack_into('<Q', volume, 264 - 32, flags)
    volume[704 - 32:704 - 32 + 8] = b'Hardware'
    struct.pack_into('<H', volume, 964 - 32, role)
    blocks[7] = checksummed(obj(1026, 1, 0xd, bytes(volume)))
    volumes = [(1026, 7)]
    if extra_volume:
        preboot = bytearray(volume)
        struct.pack_into('<H', preboot, 964 - 32, 0x10)
        blocks[11] = checksummed(obj(1030, 1, 0xd, bytes(preboot)))
        volumes.append((1030, 11))
    blocks[6] = node([(struct.pack('<QQ', oid, 1), struct.pack('<IIQ', 0, BS, block))
                      for oid, block in volumes], True, oid=6)
    blocks[5] = checksummed(obj(5, 1, 0x4000000b, struct.pack('<IIIIQ', 0, 0, 0, 0, 6)))
    total = max(next_block, 32)

    def superblock(xid):
        body = bytearray(BS - 32)
        body[0:4] = b'NXSB'
        struct.pack_into('<IQ', body, 4, BS, total)
        struct.pack_into('<II', body, 104 - 32, 2, 0)
        struct.pack_into('<Q', body, 112 - 32, 1)
        struct.pack_into('<Q', body, 160 - 32, 5)
        struct.pack_into('<I', body, 180 - 32, 100)
        for index, (oid, _) in enumerate(volumes):
            struct.pack_into('<Q', body, 184 - 32 + 8 * index, oid)
        return checksummed(obj(1, xid, 0x80000001, bytes(body)))

    blocks[0] = blocks[1] = superblock(1)
    image = bytearray(total * BS)
    for number, block in blocks.items():
        image[number * BS:(number + 1) * BS] = block
    return bytes(image)


def drec_key(parent, name, hashed):
    name += b'\0'
    if hashed:
        return fs_key(parent, 9, struct.pack('<I', len(name) | 0x1234 << 10) + name)
    return fs_key(parent, 9, struct.pack('<H', len(name)) + name)


def drec(oid, kind):
    return struct.pack('<QQH', oid, 0, kind)


def inode(oid, size, bsd_flags=0):
    fixed = bytearray(92)
    struct.pack_into('<QQ', fixed, 0, 1, oid)
    struct.pack_into('<I', fixed, 68, bsd_flags)
    if not size:
        return bytes(fixed) + struct.pack('<HH', 0, 0)
    return bytes(fixed) + struct.pack('<HHBBH', 1, 40, 8, 0, 40) + struct.pack('<QQQQQ', size, 0, 0, 0, 0)


def reader(image):
    return lambda offset, length: image[offset:offset + length]


# ---------------------------------------------------------------- tests

class ContainerTests(unittest.TestCase):
    def test_the_factory_cache_is_read_from_the_hardware_volume(self):
        files = records()
        files[f'FSC2-{SENSOR}'] = FACTORY + bytes(2 * BS)  # spans blocks
        self.assertEqual(helper.Container(reader(apfs(files))).hardware(), files)

    def test_unhashed_directory_keys_are_read(self):
        files = records()
        self.assertEqual(helper.Container(reader(apfs(files, hashed=False))).hardware(), files)

    def test_unsupported_layouts_are_refused(self):
        image = apfs(records())
        for name, bad in {
            'not APFS': bytes(len(image)),
            # A byte in a tree node's free space: only the checksum notices.
            'checksum': image[:10 * BS + 2000] + b'\xff' + image[10 * BS + 2001:],
            'encrypted volume': apfs(records(), flags=0),
            'compressed record': apfs(records(), bsd_flags=0x20),
            'no Hardware volume': apfs(records(), role=0x10, extra_volume=False),
            'no factory cache': apfs(records(), path=('FactoryData',)),
        }.items():
            with self.subTest(name), self.assertRaises(helper.Refused):
                helper.Container(reader(bad)).hardware()

    def test_the_newest_valid_checkpoint_is_used(self):
        image = bytearray(apfs(records()))
        stale = bytearray(image[0:BS])
        struct.pack_into('<Q', stale, 160, 2)  # an older checkpoint's map is gone
        image[0:BS] = checksummed(bytes(stale))
        newest = bytearray(image[BS:2 * BS])
        struct.pack_into('<Q', newest, 16, 5)
        image[BS:2 * BS] = checksummed(bytes(newest))
        self.assertEqual(helper.Container(reader(bytes(image))).hardware(), records())
        image[BS + 200] ^= 1  # a damaged newest checkpoint is skipped
        with self.assertRaises(helper.Refused):
            helper.Container(reader(bytes(image))).hardware()


class ManifestTests(unittest.TestCase):
    def test_properties_are_walked_as_der(self):
        objects = helper.manifest(seal())
        self.assertEqual(objects[b'MANP'][b'SrNm'], (0x04, SERIAL))
        self.assertEqual(objects[b'FSC2'][b'DGST'], (0x04, hashlib.sha384(CALIBRATION).digest()))

    def test_digest_bytes_hidden_in_an_opaque_value_are_not_properties(self):
        hidden = text(b'DGST') + octets(hashlib.sha384(CALIBRATION).digest()) + \
            text(b'SrNm') + octets(SERIAL)
        manifest = im4m({b'MANP': {b'blob': octets(hidden)}, b'FSC2': {b'blob': octets(hidden)}})
        objects = helper.manifest(manifest)
        self.assertNotIn(b'DGST', objects[b'FSC2'])
        self.assertNotIn(b'SrNm', objects[b'MANP'])
        with self.assertRaises(helper.Refused):
            helper.admit(records(**{f'seal-{CHIP:08X}-{ECID:016X}': manifest}), IDENTITY)

    def test_duplicate_and_malformed_properties_are_refused(self):
        digest = octets(hashlib.sha384(CALIBRATION).digest())
        twice = private(b'FSC2', der(0x31, private(b'DGST', digest) + private(b'DGST', digest)))
        duplicate = der(0x30, text(b'IM4M') + der(0x02, b'\0')
                        + der(0x31, private(b'MANB', der(0x31, twice)))
                        + octets(b'sig') + der(0x30, b''))
        misnamed = seal().replace(text(b'SrNm'), text(b'SrNx'))
        long_length = bytes([0x30, 0x81, 0x05]) + seal()[2:7]
        for name, bad in {'duplicate': duplicate, 'misnamed': misnamed,
                          'non-minimal length': long_length,
                          'trailing data': seal() + b'\0',
                          'no signature': der(0x30, text(b'IM4M') + der(0x02, b'\0')
                                              + der(0x31, private(b'MANB', der(0x31, b''))))}.items():
            with self.subTest(name), self.assertRaises(helper.Refused):
                helper.manifest(bad)

    def test_records_must_be_exactly_one_element(self):
        for name, check, data in [('combined', helper.combined, EXPECTED),
                                  ('image', lambda d: helper.image(d, b'FSC2'), FACTORY)]:
            check(data)
            with self.subTest(name), self.assertRaises(helper.Refused):
                check(data + b'\0')

    def test_distinct_objects_may_each_carry_a_digest(self):
        objects = helper.manifest(seal())
        self.assertIn(b'DGST', objects[b'FSC2'])
        self.assertIn(b'DGST', objects[b'MSRk'])

    def test_der_limits(self):
        deep = b'\x04\x00'
        for _ in range(helper.DER_MAX_DEPTH + 2):
            deep = der(0x30, deep)
        with self.assertRaises(helper.Refused):
            helper.combined(deep)
        many = der(0x30, text(b'comb') + b'\x05\x00' * (helper.DER_MAX_NODES + 1))
        with self.assertRaises(helper.Refused):
            helper.combined(many)


class AdmissionTests(unittest.TestCase):
    def test_this_macs_records_rebuild_the_sealed_calibration(self):
        expected, evidence = helper.admit(records(), IDENTITY)
        self.assertEqual(expected, EXPECTED)
        self.assertEqual(evidence['trust_sha256'], hashlib.sha256(TRUST).hexdigest())
        self.assertEqual(evidence['source_sha384'], hashlib.sha384(FACTORY).hexdigest())

    def test_the_current_trust_bundle_is_chosen_over_an_old_one(self):
        expected, _ = helper.admit(records(), IDENTITY)
        self.assertEqual(helper.combined(expected)[1], TRUST)

    def test_trust_bundle_admission(self):
        named = f'trustobject-{hashlib.sha256(TRUST).hexdigest().upper()}'
        old = f'trustobject-{hashlib.sha256(OLD_TRUST).hexdigest().upper()}'
        for name, changes in {
            'arbitrary bytes as current': {'trustobject-current': b'not a trust bundle'},
            'current without its named copy': {named: None},
            'named copy with other bytes': {'trustobject-current': TRUST, named: OLD_TRUST},
            'no current, two named': {'trustobject-current': None},
            'no current, misnamed': {'trustobject-current': None, old: None, named: OLD_TRUST},
        }.items():
            with self.subTest(name), self.assertRaises(helper.Refused):
                helper.admit(records(**changes), IDENTITY)
        expected, _ = helper.admit(records(**{'trustobject-current': None, old: None}), IDENTITY)
        self.assertEqual(expected, EXPECTED)

    def test_identity_must_be_known_and_match(self):
        other_seal = f'seal-{CHIP:08X}-{OTHER_ECID:016X}'
        for name, (changes, identity) in {
            'unknown ECID': ({}, (CHIP, None, SERIAL)),
            'unknown serial': ({}, (CHIP, ECID, None)),
            'another ECID': ({}, (CHIP, OTHER_ECID, SERIAL)),
            "another Mac's seal": ({f'seal-{CHIP:08X}-{ECID:016X}': None, other_seal: seal()}, IDENTITY),
            'another serial': ({f'seal-{CHIP:08X}-{ECID:016X}': seal(serial=b'OTHERSERIAL')}, IDENTITY),
            'two seals': ({other_seal: seal()}, IDENTITY),
        }.items():
            with self.subTest(name), self.assertRaises(helper.Refused):
                helper.admit(records(**changes), identity)

    def test_the_seal_must_cover_this_calibration(self):
        with self.assertRaises(helper.Refused):
            helper.admit(records(**{f'seal-{CHIP:08X}-{ECID:016X}': seal(payload=OTHER)}), IDENTITY)

    def test_a_changed_calibration_or_seal_changes_the_rebuild(self):
        changed = img4(OTHER, im4m({b'MANP': {}}))
        expected, _ = helper.admit(records(**{f'FSC2-{SENSOR}': changed,
                                              f'seal-{CHIP:08X}-{ECID:016X}': seal(payload=OTHER)}),
                                   IDENTITY)
        self.assertEqual(expected, sealed(OTHER))

    def test_a_manifest_only_change_is_recorded(self):
        refreshed = img4(CALIBRATION, im4m({b'MANP': {b'srvn': octets(b'\x02')}}))
        expected, evidence = helper.admit(records(**{f'FSC2-{SENSOR}': refreshed}), IDENTITY)
        self.assertEqual(expected, EXPECTED)  # the enclave loads only the IM4P
        self.assertEqual(evidence['source_sha384'], hashlib.sha384(refreshed).hexdigest())


class IdentityTests(unittest.TestCase):
    def test_live_identity_comes_from_the_local_policy_and_the_device_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            sep = tree / 'soc' / 'sep@3aa600000'
            sep.mkdir(parents=True)
            (sep / 'compatible').write_bytes(b'apple,sep\0')
            (sep / 'local-policy-manifest').write_bytes(
                im4m({b'MANP': {b'CHIP': integer(CHIP), b'ECID': integer(ECID)}}))
            self.assertEqual(helper.live_identity(tree), (CHIP, ECID, None))
            (tree / 'serial-number').write_bytes(SERIAL + b'\0')
            self.assertEqual(helper.live_identity(tree), IDENTITY)
            (sep / 'local-policy-manifest').write_bytes(b'junk')
            self.assertEqual(helper.live_identity(tree), (None, None, SERIAL))


class PrepareTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state, self.run = self.root / 'state', self.root / 'run'
        self.firmware = self.root / 'firmware'
        self.target = self.firmware / 'apple' / 'mesacal-j713.bin'
        self.carved = self.root / 'carved.bin'
        self.extractor = self.root / 'extract'
        self.extractor.write_text('#!/bin/sh\n[ -f "$CARVED" ] || exit 1\ncp "$CARVED" "$3" && chmod 600 "$3"\n')
        self.extractor.chmod(0o755)
        os.environ['CARVED'] = str(self.carved)
        self.addCleanup(os.environ.pop, 'CARVED', None)
        self.image = apfs(records())

    def prepare(self, identity=IDENTITY):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            ready = helper.prepare(reader(self.image), self.root / 'device', self.state, self.run,
                                   self.firmware, 'apple/mesacal-j713.bin', self.extractor, identity)
        self.output = out.getvalue()
        self.assertEqual(ready, (self.run / helper.READY).exists())
        return ready

    def install(self, data, mode=0o600):
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_bytes(data)
        self.target.chmod(mode)

    def evidence(self, kind):
        directory = self.state / kind
        return sorted(p.read_bytes() for p in directory.iterdir()) if directory.exists() else []

    def assert_ready_for(self, data):
        self.assertEqual(self.target.read_bytes(), data)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        marker = json.loads((self.run / helper.READY).read_text())
        self.assertEqual(marker['sha256'], hashlib.sha256(data).hexdigest())
        self.assertTrue(calibration_ready.ready(str(self.run / helper.READY)))

    def test_the_rebuilt_record_is_installed_and_marked_ready(self):
        self.assertTrue(self.prepare())
        self.assert_ready_for(EXPECTED)
        self.assertEqual(self.evidence('rollback'), [])

    def test_an_identical_record_is_kept_and_its_mode_secured(self):
        self.install(EXPECTED, 0o644)
        before = self.target.stat().st_ino
        self.assertTrue(self.prepare())
        self.assert_ready_for(EXPECTED)
        self.assertEqual(self.target.stat().st_ino, before)

    def test_each_start_reads_the_current_records(self):
        self.prepare()
        self.image = apfs(records(**{f'FSC2-{SENSOR}': img4(OTHER, im4m({b'MANP': {}})),
                                     f'seal-{CHIP:08X}-{ECID:016X}': seal(payload=OTHER)}))
        self.assertTrue(self.prepare())
        self.assert_ready_for(sealed(OTHER))
        self.assertEqual(self.evidence('rollback'), [EXPECTED])

    def test_a_new_trust_bundle_replaces_the_installed_record(self):
        self.install(sealed(trust=OLD_TRUST))
        self.assertTrue(self.prepare())
        self.assert_ready_for(EXPECTED)
        self.assertEqual(self.evidence('rollback'), [sealed(trust=OLD_TRUST)])

    def test_a_damaged_or_open_record_is_replaced_never_with_the_bare_image(self):
        for name, data, mode in [('damaged header', b'\x31' + EXPECTED[1:], 0o600),
                                 ('world readable', sealed(trust=OLD_TRUST), 0o644),
                                 ('bare image', FACTORY, 0o600)]:
            with self.subTest(name):
                self.install(data, mode)
                self.assertTrue(self.prepare())
                self.assert_ready_for(EXPECTED)
                self.assertNotEqual(self.target.read_bytes(), FACTORY)

    def test_a_link_at_the_target_is_quarantined_not_followed(self):
        outside = self.root / 'outside'
        outside.write_bytes(b'keep')
        self.target.parent.mkdir(parents=True)
        self.target.symlink_to(outside)
        self.assertTrue(self.prepare())
        self.assert_ready_for(EXPECTED)
        self.assertEqual(outside.read_bytes(), b'keep')
        self.assertEqual(self.evidence('rollback') + self.evidence('quarantine'), [])

    def test_a_failed_replacement_leaves_the_old_record_and_no_readiness(self):
        old = sealed(trust=OLD_TRUST)
        self.install(old)
        real = helper.atomic_write

        def fail_on_target(path, data, mode=0o600):
            if path == self.target:
                raise OSError('disk full')
            real(path, data, mode)

        with patch.object(helper, 'atomic_write', side_effect=fail_on_target):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertEqual(self.target.read_bytes(), old)
        self.assertEqual(self.evidence('rollback'), [old])
        self.assertFalse((self.run / helper.READY).exists())

    def test_refusal_quarantines_another_macs_record_and_stays_unready(self):
        foreign = sealed(manifest=seal(serial=b'OTHERSERIAL'))
        self.install(foreign)
        self.assertFalse(self.prepare(identity=(CHIP, OTHER_ECID, SERIAL)))
        self.assertFalse(self.target.exists())
        self.assertEqual(self.evidence('quarantine'), [foreign])
        self.assertIn('refresh', self.output)

    def test_unknown_identity_leaves_a_plausible_record_but_unready(self):
        self.install(EXPECTED)
        self.assertFalse(self.prepare(identity=(CHIP, ECID, None)))
        self.assertEqual(self.target.read_bytes(), EXPECTED)
        self.assertEqual(self.evidence('quarantine'), [])

    def test_an_unreadable_container_quarantines_a_bare_image(self):
        self.image = bytes(len(self.image))
        self.carved.write_bytes(FACTORY)
        self.install(FACTORY)
        self.assertFalse(self.prepare())
        self.assertFalse(self.target.exists())
        self.assertEqual(self.evidence('quarantine'), [FACTORY])
        self.assertIn('the boot container is not APFS', self.output)

    def test_readiness_is_cleared_before_each_attempt(self):
        self.assertTrue(self.prepare())
        self.image = apfs(records(**{'trustobject-current': b'not a trust bundle'}))
        self.assertFalse(self.prepare())
        self.assertFalse((self.run / helper.READY).exists())

    def test_readiness_follows_the_installed_bytes(self):
        self.prepare()
        marker = str(self.run / helper.READY)
        self.target.write_bytes(sealed(trust=OLD_TRUST))
        self.assertFalse(calibration_ready.ready(marker))
        self.target.write_bytes(EXPECTED)
        self.target.chmod(0o644)
        with self.assertRaises(OSError):
            calibration_ready.ready(marker)

    def test_an_fscl_record_is_installed_as_it_is(self):
        self.image = apfs({'HmCA-0': b'unrelated'})
        for fscl in FSCL_RECORDS:
            with self.subTest(len(fscl)):
                self.carved.write_bytes(fscl)
                self.assertTrue(self.prepare())
                self.assert_ready_for(fscl)

    def test_an_installed_fscl_record_is_never_quarantined(self):
        for fscl in FSCL_RECORDS:
            self.assertIsNone(helper.installed_problem(fscl, SERIAL))
        with self.assertRaises(helper.Refused):
            helper.fscl_record(comb(img4(im4p(b'CALB', b'FSC2'), im4m({})), TRUST))

    def test_a_sensorless_mac_installs_nothing(self):
        self.image = apfs({'HmCA-0': b'unrelated'})
        with self.assertRaises(helper.subprocess.CalledProcessError):
            self.prepare()
        self.assertFalse(self.target.exists())
        self.assertFalse((self.run / helper.READY).exists())

    def test_state_and_firmware_links_are_refused(self):
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        self.state.symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.prepare()
        self.state.unlink()
        self.firmware.mkdir()
        (self.firmware / 'apple').symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_firmware_name_comes_from_the_device_tree(self):
        sensor = self.root / 'dt' / 'spi' / 'fingerprint@0'
        sensor.mkdir(parents=True)
        (sensor / 'compatible').write_bytes(b'apple,mesa-fingerprint\0')
        (sensor / 'firmware-name').write_bytes(b'apple/mesacal-j713.bin\0')
        self.assertEqual(helper.firmware_name(self.root / 'dt'), 'apple/mesacal-j713.bin')
        (sensor / 'firmware-name').write_bytes(b'apple/../../escape.bin\0')
        with self.assertRaises(ValueError):
            helper.firmware_name(self.root / 'dt')


if __name__ == '__main__':
    unittest.main()
