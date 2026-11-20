#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Fail-closed Stage 2 updates. Only the shell entry point mounts the ESP.

Kernel packages declare the DT ABI generation their trees use and require.
An older retained generation cannot boot with a newer shared tree generation.

Stage 2 is written only to the file this boot shows Stage 1 loads, and never
with an aura older than the running Stage 2 (fedora-aurora#452).
"""
import argparse
import functools
import glob
import fnmatch
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile


class Refused(RuntimeError):
    pass


# aura's version tags (aura's version.sh): its VERSION, then -g<commit> off a
# release tag and -dirty. A point release such as 1.0.0b13.1 follows its beta.
AURA_TAG = re.compile(r'(?:aura[- v]?)?v?(\d+)\.(\d+)\.(\d+)(?:b(\d+))?(?:\.(\d+))?'
                      r'(?:-(?:[0-9]+-)?g[0-9a-f]+)?(?:-dirty)?')
TRIAL_STAGE1 = (1, 0, 0, 0, 4, 0)       # aura-try
RECORDING_STAGE1 = (1, 0, 0, 0, 12, 0)  # records the image it loads (aura secboot.c)


def aura_release(version, aura=False):
    """An aura release as a tuple that sorts as releases do, or None.

    1.0.0b13 < 1.0.0b13.1 < 1.0.0 < 1.0.1b1. The build (-g<commit>, -dirty) is
    left out: two builds of one release have no order anyone can read. Unless
    `aura` says the version is aura's, one without a beta number counts only
    when it starts with aura or 1.0.0: Asahi's m1n1 (1.4.x, 1.6.1) uses other
    numbers for other code.
    """
    match = AURA_TAG.fullmatch(version or '')
    if not match or (match[4] is None and not aura and
                     not version.startswith(('aura', '1.0.0', 'v1.0.0'))):
        return None
    major, minor, patch = map(int, match.group(1, 2, 3))
    beta = match[4]
    return (major, minor, patch, 0 if beta is not None else 1, int(beta or 0), int(match[5] or 0))


def aura_tag(image):
    """The version an aura image was built as: the text after its ##aura_ver## marker (aura's main.c)."""
    start = image.find(b'##aura_ver##')
    if start < 0:
        return None
    start += len(b'##aura_ver##')
    end = image.find(b'\0', start, start + 129)
    tag = image[start:end] if end >= 0 else b''
    return tag.decode('ascii') if re.fullmatch(rb'[A-Za-z0-9._+-]+', tag) else None


def loaded_digest(image):
    """SHA-256 of what a loading aura stage measures: the image before its aura_sig trailer, if any."""
    if len(image) >= 16 and image[-8:] == b'AURSIGT1':
        offset = int.from_bytes(image[-16:-8], 'little')
        if offset < len(image) - 16 and image[offset:offset + 8] == b'aura_sig':
            image = image[:offset]
    return hashlib.sha256(image).hexdigest()


class Tree(dict):
    def __init__(self):
        super().__init__()
        self.boards = {}

    def proof(self, board):
        if board is None:
            return dict(self)
        return {name: data for name, data in self.items() if board in self.boards[name]}


# FDT structure block tokens
FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9


def dtb_nodes(blob):
    """Every node path in a validated FDT, spelled exactly.

    fdtget resolves a component without a unit address, such as /soc, to the
    first soc@... sibling. T6050 trees have soc@200000000, soc@2308000000 and
    soc, so a node under the plain soc looked missing.
    """
    offset = int.from_bytes(blob[8:12], 'big')
    nodes, stack = set(), []
    while True:
        token = int.from_bytes(blob[offset:offset + 4], 'big')
        offset += 4
        if token == FDT_BEGIN_NODE:
            end = blob.index(b'\0', offset)
            stack.append(blob[offset:end].decode())
            nodes.add('/' + '/'.join(stack[1:]))
            offset = (end + 4) & ~3
        elif token == FDT_END_NODE:
            stack.pop()
        elif token == FDT_PROP:
            offset = (offset + 8 + int.from_bytes(blob[offset:offset + 4], 'big') + 3) & ~3
        elif token == FDT_END:
            return nodes
        elif token != FDT_NOP:
            raise Refused('invalid Stage 2 DTB structure')


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def replace_file(path, data):
    """Same-directory staging; exceptions never expose a partially written file."""
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)
            os.fsync(stream.fileno())
        if hashlib.sha256(staged.read_bytes()).digest() != hashlib.sha256(data).digest():
            raise Refused(f'failed read-back of {staged}')
        os.replace(staged, path)
        sync_dir(path.parent)
    finally:
        staged.unlink(missing_ok=True)


def grub_vercmp(a, b):
    """GRUB blscfg's copy of rpm's version comparison: 1 when a is newer, -1 when b is."""
    def kind(c, test):
        return c.isascii() and test(c)
    if a == b:
        return 0
    i = j = 0
    while i < len(a) or j < len(b):
        while i < len(a) and not kind(a[i], str.isalnum) and a[i] not in '~+':
            i += 1
        while j < len(b) and not kind(b[j], str.isalnum) and b[j] not in '~+':
            j += 1
        one, two = a[i:i + 1], b[j:j + 1]
        if '~' in (one, two):
            if one != '~':
                return 1
            if two != '~':
                return -1
            i, j = i + 1, j + 1
            continue
        if '+' in (one, two):
            if not one:
                return -1
            if not two:
                return 1
            if one != '+':
                return 1
            if two != '+':
                return -1
            i, j = i + 1, j + 1
            continue
        if not (one and two):
            break
        numeric = kind(one, str.isdigit)
        test = str.isdigit if numeric else str.isalpha
        end1, end2 = i, j
        while end1 < len(a) and kind(a[end1], test):
            end1 += 1
        while end2 < len(b) and kind(b[end2], test):
            end2 += 1
        first, second = a[i:end1], b[j:end2]
        if not second:
            # Numeric segments are newer than alphabetic ones.
            return 1 if numeric else -1
        if numeric:
            first, second = first.lstrip('0'), second.lstrip('0')
            if len(first) != len(second):
                return 1 if len(first) > len(second) else -1
        if first != second:
            return 1 if first > second else -1
        i, j = end1, end2
    if i >= len(a) and j >= len(b):
        return 0
    return -1 if i >= len(a) else 1


def grub_entry_cmp(a, b):
    """GRUB's order of two BLS entry ids: name, version and release, split at the last two dashes."""
    def split(value):
        rest, dash, release = value.rpartition('-')
        if not dash:
            rest, release = value, None
        name, dash, version = rest.rpartition('-')
        if not dash:
            name, version = rest, None
        if version is None:
            version, release = release, None
        return name, version or '', release or ''
    for first, second in zip(split(a), split(b)):
        result = grub_vercmp(first, second)
        if result:
            return result
    return 0


class Update:
    def __init__(self, root=Path('/'), env=None):
        self.root = Path(root)
        self.env = os.environ if env is None else env
        self.action = self.env.get('AURORA_KERNEL_ACTION', 'refresh')
        self.version = self.env.get('AURORA_KERNEL_VERSION', '')
        self.held = None  # Why this run left Stage 2 as it is, once it has.
        if self.action not in ('refresh', 'add', 'remove'):
            raise Refused('unknown kernel action')
        if self.action != 'refresh':
            self.validate_version(self.version)

    @staticmethod
    def validate_version(version):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+~-]*', version):
            raise Refused(f'invalid kernel version: {version!r}')

    def path(self, path):
        return self.root / str(path).lstrip('/')

    def compatibles(self):
        path = self.path(self.env.get('AURORA_DEVICE_TREE_COMPATIBLE', '/proc/device-tree/compatible'))
        return [value.decode('ascii') for value in path.read_bytes().split(b'\0') if value] if path.exists() else []

    def board(self):
        values = self.compatibles()
        boards = [value for value in values if re.fullmatch(r'apple,[jk][a-z0-9]+', value)]
        if boards:
            return boards[0]
        if any(value.startswith('apple,') for value in values):
            raise Refused('cannot identify the Apple board')
        return None  # Image builds validate the entire selected set.

    def ctxr_board(self):
        marker = self.path(self.env.get('AURORA_MONITOR_FREE_MARKER', '/usr/share/aura/monitor-free'))
        patterns = ('apple,t81[3-9a-f]?', 'apple,t8[2-9a-f]??',
                    'apple,t60[4-9a-f]?', 'apple,t6[1-9a-f]??')
        if marker.exists() and any(fnmatch.fnmatchcase(value, pattern)
                                   for value in self.compatibles() for pattern in patterns):
            return self.board()
        return None

    def target(self):
        name = self.env.get('TARGET')
        if not name:
            raise Refused('the entry point has not mounted a target ESP')
        target = self.path(name)
        if self.ctxr_board() and target.name == 'boot.bin':
            target = target.with_name('boot-ctxr.bin')
        return target

    def kernel_images(self):
        images = {p.parent.name: p for p in self.path('/usr/lib/modules').glob('*/vmlinuz')}
        for p in self.path('/boot').glob('vmlinuz-*'):
            images.setdefault(p.name.removeprefix('vmlinuz-'), p)
        # BLS entries can retain kernels which no longer have modules. Those
        # must not silently disappear from the compatibility check.
        for p in self.path('/boot/loader/entries').glob('*.conf'):
            fields = self.bls_fields(p)
            version = fields.get('version')
            if version:
                self.validate_version(version)
                if version not in images and self.entry_image_gone(fields):
                    # GRUB cannot load this entry's kernel, so no tree has to
                    # suit it. Such entries outlive a kernel removed without
                    # kernel-install, as Asahi kernels were on migration.
                    print(f'update-m1n1: ignoring boot entry {p.name}: its kernel '
                          f'{fields["linux"].strip()} does not exist', file=sys.stderr)
                    continue
                images.setdefault(version, self.path('/boot/vmlinuz-' + version))
        if self.action == 'add':
            images.setdefault(self.version, self.path(f'/usr/lib/modules/{self.version}/vmlinuz'))
        if self.action == 'remove':
            images.pop(self.version, None)
        return images

    @staticmethod
    def bls_fields(path):
        return dict(line.split(None, 1) for line in path.read_text().splitlines()
                    if len(line.split(None, 1)) == 2 and not line.startswith('#'))

    def machine_id(self):
        machine = self.env.get('KERNEL_INSTALL_MACHINE_ID', '')
        path = self.path('/etc/machine-id')
        if not machine and path.is_file():
            machine = path.read_text().strip()
        return machine

    def boot_menu(self, images):
        """GRUB's BLS menu as (id, version, title), in the order GRUB lists it.

        blscfg sorts entries by id, newest first, comparing as rpm does.
        kernel-install writes an added kernel's entry after this hook. With
        no entries at all, every kernel counts as one.
        """
        menu = {}
        for p in self.path('/boot/loader/entries').glob('*.conf'):
            fields = self.bls_fields(p)
            version = fields.get('version', '').strip()
            if version in images and fields.get('linux', '').strip():
                menu[p.name.removesuffix('.conf')] = (version, fields.get('title', '').strip())
        machine = self.machine_id()
        def entry(version):
            return f'{machine}-{version}' if machine else version
        if not menu:
            menu = {entry(version): (version, '') for version in images}
        elif self.action == 'add' and self.version not in (v for v, _ in menu.values()):
            menu[entry(self.version)] = (self.version, '')
        order = sorted(menu, key=functools.cmp_to_key(grub_entry_cmp), reverse=True)
        return [(name, *menu[name]) for name in order]

    def entry_image_gone(self, fields):
        """True when a BLS entry names a kernel that exists nowhere GRUB looks.

        Its `linux` path is relative to the file system holding the entries:
        a separate /boot, or the root with /boot in the path.
        """
        image = fields.get('linux', '').strip()
        if not image:
            return False
        relative = image.lstrip('/')
        return not any(self.path(base + relative).exists() for base in ('/boot/', '/'))

    def dtb_dir(self, version):
        self.validate_version(version)
        for path in (f'/usr/lib/modules/{version}/dtb', f'/boot/dtb-{version}'):
            if self.path(path).is_dir():
                return self.path(path)
        raise Refused(f'kernel {version} has no DTB directory')

    def generation(self, version):
        self.validate_version(version)
        marker = self.path(f'/usr/lib/modules/{version}/dtb-abi')
        try:
            value = marker.read_text(encoding='ascii')
        except FileNotFoundError:
            # Kernels from before the marker share generation 1: declaring it
            # changed no device tree, and they booted the trees that followed.
            return 1
        if not re.fullmatch(r'(0|[1-9][0-9]*)\n?', value):
            raise Refused(f'invalid DT ABI generation for kernel {version} in {marker}')
        return int(value)

    def tree(self, expression):
        directory = Path(expression)
        if directory.is_dir():
            directory = directory / 'apple' if (directory / 'apple').is_dir() else directory
            paths = sorted(set(directory.glob('t6*.dtb')) | set(directory.glob('t81*.dtb')))
        else:
            # Keep the historical whitespace-separated glob configuration.
            paths = []
            for pattern in str(expression).split():
                matched = sorted(map(Path, glob.glob(pattern)))
                if not matched:
                    raise Refused(f'DTB pattern has no matches: {pattern}')
                paths.extend(matched)
        if not paths:
            raise Refused(f'no Apple DTBs in {expression}')
        result = Tree()
        for path in paths:
            data = path.read_bytes()
            validation = subprocess.run(['dtc', '-I', 'dtb', '-O', 'dtb', '-o', os.devnull],
                                        input=data, capture_output=True)
            if validation.returncode or not data:
                raise Refused(f'invalid DTB: {path}')
            compatible = subprocess.check_output(['fdtget', '-t', 's', str(path), '/', 'compatible'],
                                                 stderr=subprocess.DEVNULL, text=True).split()
            boards = [v for v in compatible if re.fullmatch(r'apple,[jk][a-z0-9]+', v)]
            if not boards:
                raise Refused(f'DTB has no Apple board compatible: {path}')
            if path.name in result:
                raise Refused(f'duplicate DTB filename {path.name} in {expression}')
            # A set may contain multiple variants of the same board. Keep
            # every variant and its original filename order, as the vendor
            # updater does, rather than silently selecting a different one.
            result[path.name] = data
            result.boards[path.name] = boards
        return result

    @staticmethod
    def shell_assignments(path):
        values = {}
        if path.is_file():
            for line in path.read_text(errors='replace').splitlines():
                match = re.fullmatch(r'\s*([A-Za-z_][A-Za-z0-9_]*)=(["\']?)(.*?)\2\s*', line)
                if match:
                    values[match[1]] = match[3]
        return values

    def grub_default(self):
        """Return the GRUB default entry id and where it came from, or None.

        custom.cfg is sourced last by grub.cfg, so its `set default=` wins over
        /etc/default/grub and the saved_entry in grubenv.
        """
        for directory in ('/boot/grub2', '/boot/grub'):
            custom = self.path(directory + '/custom.cfg')
            if custom.is_file():
                found = re.findall(r'^\s*set\s+default=(["\']?)([^"\'\s]+)\1\s*$',
                                   custom.read_text(errors='replace'), re.M)
                found = [value for _, value in found if '$' not in value]
                if found:
                    return found[-1], str(custom.relative_to(self.root))
        configured = self.shell_assignments(self.path('/etc/default/grub')).get('GRUB_DEFAULT', 'saved')
        if configured != 'saved':
            return (configured, 'GRUB_DEFAULT') if configured else None
        for name in ('/boot/grub2/grubenv', '/boot/grub/grubenv', '/boot/efi/EFI/fedora/grubenv'):
            entry = self.shell_assignments(self.path(name)).get('saved_entry')
            if entry:
                return entry, 'saved_entry'
        return None

    def default_kernel(self, images, menu):
        """The installed kernel GRUB boots by default, or None if it boots its first entry."""
        default = self.grub_default()
        if not default:
            return None
        entry, origin = default
        if re.fullmatch(r'\d+', entry):
            index = int(entry)
            return menu[index][1] if index < len(menu) else None
        for name, version, title in menu:
            if entry == name or (title and entry == title):
                return version
        # BLS ids are <machine-id>-<version>; hand-written menu entries in
        # custom.cfg commonly end in the version too.
        matches = [v for v in images if entry == v or entry.endswith('-' + v)]
        if matches:
            return max(matches, key=len)
        print(f'update-m1n1: GRUB default {entry!r} ({origin}) is not an installed kernel; '
              f'GRUB boots its first entry, kernel {menu[0][1]}', file=sys.stderr)
        return None

    def select_kernel(self, images, menu):
        newest = menu[0][1]
        default = self.default_kernel(images, menu)
        if self.action == 'add':
            pinned = self.grub_default()
            kernel = self.shell_assignments(self.path('/etc/sysconfig/kernel'))
            # Fedora's kernel-install makes a new kernel the saved default
            # unless UPDATEDEFAULT says otherwise; a custom.cfg default stays.
            becomes_default = (kernel.get('UPDATEDEFAULT', 'yes') == 'yes'
                               and not (pinned and pinned[1].endswith('custom.cfg')))
            if becomes_default or default is None:
                return self.version
            selected = default
        else:
            selected = default or newest
        if selected != newest:
            print(f'update-m1n1: composing Stage 2 from the default kernel {selected}, '
                  f'not the newer non-default {newest}', file=sys.stderr)
        return selected

    def plan(self):
        images = self.kernel_images()
        if not images:
            raise Refused('no remaining installed kernels; preserving Stage 2 and /boot/dtb')
        selected = self.select_kernel(images, self.boot_menu(images))
        source = self.dtb_dir(selected)
        configured = self.env.get('DTBS', '/boot/dtb')
        if not configured.strip():
            raise Refused('DTBS config unset or empty')
        expression = source if configured == '/boot/dtb' else ' '.join(
            str(self.path(pattern)) for pattern in configured.split())
        candidate = self.tree(expression)
        board = self.board()
        proof = candidate.proof(board)
        if not proof:
            raise Refused(f'selected DTBs have no {board}')
        trees = {}
        generations = {version: self.generation(version) for version in images}
        for version, image in images.items():
            if not image.is_file():
                raise Refused(f'kernel image missing for BLS entry {version}')
            try:
                own = self.tree(self.dtb_dir(version))
            except Refused:
                # Fedora's rescue image is a copy of an installed kernel. Use
                # its original tree only when the complete images match.
                if not version.startswith('0-rescue-'):
                    raise
                matches = [v for v, p in images.items() if not v.startswith('0-rescue-')
                           and p.is_file() and p.read_bytes() == image.read_bytes()]
                if not matches:
                    raise Refused(f'rescue kernel {version} has no provable DTB source')
                own = self.tree(self.dtb_dir(matches[0]))
            trees[version] = own
        generation = generations[selected]
        if configured != '/boot/dtb':
            # Custom trees must have a known declaration too. Match the board
            # set to installed trees, rather than guessing an ABI from a path
            # or trusting arbitrary DTBS bytes as the selected kernel's ABI.
            matches = [generations[v] for v, tree in trees.items() if tree.proof(board) == proof]
            if not matches:
                raise Refused('custom DTBS have no installed DT ABI source')
            generation = max(matches)
        self.selected_generation = generation
        older = sorted(v for v in images if generations[v] < generation)
        if older:
            kernels = ', '.join(f'{v} (generation {generations[v]})' for v in older)
            command = 'sudo dnf remove ' + ' '.join(f"'/{images[v].relative_to(self.root)}'" for v in older)
            raise Refused(f'selected DTBs use DT ABI generation {generation}, but retained kernels '
                          f'{kernels} require an older generation. Stage 2 and /boot/dtb are kept. '
                          f'After verifying a working compatible fallback, remove the listed kernels '
                          f'with `{command}` and run `sudo update-m1n1` again. '
                          'No fallback kernel is removed automatically.')
        # An administrator-owned real /boot/dtb must never be replaced.
        link = self.path('/boot/dtb')
        if link.exists() and not link.is_symlink():
            raise Refused('/boot/dtb is not a symlink')
        m1n1 = self.path(self.env.get('M1N1', '/usr/lib64/m1n1/m1n1.bin')).read_bytes()
        uboot = self.path(self.env.get('U_BOOT', '/usr/share/uboot/apple_m1/u-boot-nodtb.bin')).read_bytes()
        if not m1n1 or not uboot:
            raise Refused('empty aura or U-Boot input')
        options = []
        config = self.path(self.env.get('CONFIG', '/etc/m1n1.conf'))
        if config.exists():
            for line in config.read_bytes().splitlines():
                if re.match(rb'^(chosen\.[^=]+|display|mitigations)=', line):
                    options.append(line + b'\n')
        # Deduplicate multi-compatible trees and keep deterministic ordering.
        ctxr = self.ctxr_board()
        blobs = list(dict.fromkeys(candidate[key] for key in sorted(candidate)
                                   if not ctxr or ctxr in candidate.boards[key]))
        payload = m1n1 + b''.join(blobs) + gzip.compress(uboot, mtime=0) + b''.join(options)
        if ctxr and len(payload) > 16 * 1024 * 1024:
            raise Refused('CTXR Stage 2 exceeds the 16 MiB slot; keeping the working images')
        return selected, source, trees[selected], payload

    def chosen(self, name):
        path = self.path('/proc/device-tree/chosen') / name
        return path.read_bytes().rstrip(b'\0').decode('ascii') if path.exists() else ''

    def stage1_version(self):
        """This boot's Stage 1 version, and whether the property names aura's.

        The aura properties are authoritative when present; aurora,aura-* is
        aura#313's name for asahi,m1n1-*, which Stage 2 writes too for a while.
        """
        for name in ('aura,stage1-version', 'aurora,aura-stage1-version'):
            if self.chosen(name):
                return self.chosen(name), True
        return self.chosen('asahi,m1n1-stage1-version'), False

    def stage2_version(self):
        """The running Stage 2's version (its ##aura_ver## tag), and whether the property names aura's."""
        if self.chosen('aurora,aura-stage2-version'):
            return self.chosen('aurora,aura-stage2-version'), True
        return self.chosen('asahi,m1n1-stage2-version'), False

    def supports_trial(self):
        # A stock m1n1 version (such as 1.6.1) does not imply aura-try support.
        if self.board() is None:
            return False
        release = aura_release(*self.stage1_version())
        return release is not None and release >= TRIAL_STAGE1

    def stage1_loaded(self):
        """The SHA-256 digests this boot's Stage 1 recorded for the image it loaded.

        A Stage 1 from aura 1.0.0b12 on measures its next stage and passes the
        entry on as chosen.aurora,measure-N. A 1.0.0b12 or later Stage 2 moves
        it into /chosen/aurora,boot-security; an older one leaves the line as a
        property (aura's secboot.c). An entry without a usable digest is ''.
        """
        chosen = self.path('/proc/device-tree/chosen')
        digests = set()
        for entry in sorted((chosen / 'aurora,boot-security').glob('measurement@*')):
            fields = {name: (entry / name).read_bytes().rstrip(b'\0') if (entry / name).is_file() else b''
                      for name in ('stage', 'component')}
            if fields == {'stage': b'stage1', 'component': b'next-stage'}:
                digest = (entry / 'sha256').read_bytes() if (entry / 'sha256').is_file() else b''
                digests.add(digest.hex() if len(digest) == 32 and any(digest) else '')
        for line in sorted(chosen.glob('aurora,measure-*')):
            fields = line.read_bytes().rstrip(b'\0').split(b';')
            if len(fields) == 7 and fields[0] == b'stage1' and fields[2] == b'next-stage':
                digest = fields[6]
                digests.add(digest.decode() if re.fullmatch(rb'[0-9a-f]{64}', digest) and digest.strip(b'0')
                            else '')
        return digests

    def esp_relative(self, path):
        esp = self.env.get('ESP_ROOT')
        if esp and path.is_relative_to(self.path(esp)):
            return path.relative_to(self.path(esp)).as_posix()
        return str(path)

    def esp_images(self, digest):
        """The ESP files a loading stage measures as `digest`: what Stage 1 loads instead."""
        esp = self.env.get('ESP_ROOT')
        if not esp:
            return []
        root, found = self.path(esp), []
        for directory, names, files in os.walk(root):  # Symlinked directories are not followed.
            names.sort()
            for name in sorted(files):
                path = Path(directory) / name
                try:
                    if (not path.is_symlink() and path.is_file() and path.stat().st_size <= 256 << 20
                            and loaded_digest(path.read_bytes()) == digest):
                        found.append(path.relative_to(root).as_posix())
                except OSError:
                    continue
        return found

    def stage1_hold(self, target):
        """Why this boot does not show that Stage 1 loads `target`, or None.

        Stage 1 loads the one ESP path in its own config, which Linux cannot
        read. A Stage 1 from aura 1.0.0b12 on records what it loaded, so the
        target must be those bytes. An older one that trials (1.0.0b4 on)
        leaves the version of the Stage 2 it started, which the target must be
        built as. Older Stage 1s, and versions nothing can read, keep the path
        aura's installer enrols: m1n1/boot.bin, or m1n1/boot-ctxr.bin from a
        padded Mach-O Stage 1.
        """
        relative = self.esp_relative(target)
        present = target.is_file() and not target.is_symlink()
        version, aura = self.stage1_version()
        release = aura_release(version, aura)
        digests = self.stage1_loaded()
        if not digests:
            if release is not None and release >= RECORDING_STAGE1:
                return (f'Stage 1 {version} records the Stage 2 it loads, but this boot has no such record, '
                        f'so it cannot be shown to load {relative}')
            if release is None or release < TRIAL_STAGE1:
                return None
            if not present:
                return f'{relative} does not exist, so Stage 1 {version} loads another file'
            running, built = self.stage2_version()[0], aura_tag(target.read_bytes())
            if running and built and running != built:
                return (f'Stage 2 {running} booted, but {relative} holds aura {built}, '
                        f'so Stage 1 {version} loads another file')
            return None
        if len(digests) != 1 or '' in digests:
            return (f"this boot's record of the Stage 2 that Stage 1 loaded is unreadable or ambiguous, "
                    f'so it cannot be shown to load {relative}')
        digest, = digests
        if present and loaded_digest(target.read_bytes()) == digest:
            return None
        trial = self.chosen('aurora,trial')
        if trial:
            return f'this boot is an aura-try trial of {trial}, so it cannot show that Stage 1 otherwise loads {relative}'
        found = self.esp_images(digest)
        where = (' or '.join(found) if found
                 else f'an image (sha256 {digest[:16]}...) that matches no file on this ESP')
        return f'Stage 1 loads {where}, not {relative}'

    def downgrade_hold(self, payload):
        """Why `payload` would take the running Stage 2 back to an older aura, or None."""
        if self.env.get('AURORA_STAGE2_ALLOW_DOWNGRADE') == '1':
            return None
        running, aura = self.stage2_version()
        built = aura_tag(payload)
        old, new = aura_release(running, aura), aura_release(built or '', aura=True)
        if old is None or new is None or new >= old:
            return None
        return (f"the candidate's aura {built} is older than the running Stage 2 {running} "
                '(AURORA_STAGE2_ALLOW_DOWNGRADE=1 allows it for one run)')

    def stage2_hold(self, target, payload):
        """Why `payload` must not be written for `target` on this boot, or None."""
        return self.stage1_hold(target) or self.downgrade_hold(payload)

    def keep(self, reason):
        self.held = reason
        print(f'update-m1n1: {reason}: not touching the boot chain; the live Stage 2 is kept', file=sys.stderr)

    def check_esp(self):
        device = self.env.get('ESP_DEVICE', '')
        if (self.env.get('ESP_FSTYPE') != 'vfat' or not device or
                not stat.S_ISBLK(os.stat(device).st_mode)):
            raise Refused('aura-try requires a mounted block-device FAT ESP')

    def trial_paths(self):
        self.check_esp()
        target = self.target()
        esp = self.path(self.env['ESP_ROOT'])
        # Resolve parent components too, so a configured symlink cannot escape
        # the mounted ESP. Never follow a final candidate/marker symlink.
        if target.is_symlink() or target.parent.resolve() != target.parent:
            raise Refused('Stage 2 target must not contain symlinks')
        relative = target.relative_to(esp).as_posix() + '.next'
        if not re.fullmatch(r'[A-Za-z0-9_./-]+', relative) or any(
                part in ('', '.', '..') for part in relative.split('/')) or len(relative) >= 128:
            raise Refused('invalid ESP-relative trial path')
        candidate = target.with_name(target.name + '.next')
        receipt = target.with_name(target.name + '.next.json')
        marker = esp / 'aura-try'
        for path in (candidate, receipt, marker):
            if path.is_symlink():
                raise Refused(f'trial file is a symlink: {path}')
        return target, candidate, receipt, marker, relative

    def flush_esp(self):
        os.sync()
        subprocess.run(['blockdev', '--flushbufs', self.env['ESP_DEVICE']], check=True)

    def marker(self, path):
        if not path.exists():
            return None
        fields = path.read_bytes().split(b'\n')
        if len(fields) != 3 or fields[0] not in (b'armed', b'spent') or fields[2]:
            raise Refused('unrecognized aura-try marker; preserving it')
        return fields[0].decode(), fields[1].decode('ascii')

    def attempts(self):
        return self.path('/var/lib/aurora-stage2/attempts')

    def attempt(self, digest):
        """Return the path and record of this candidate's automatic attempt.

        Attempts are keyed by the candidate's SHA-256, so an aura, U-Boot,
        m1n1.conf or DTB change gets its own trial even for the same kernel.
        Records from 20261107-1 are named after the kernel version; they still
        count for the candidate whose hash they contain.
        """
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise Refused('invalid Stage 2 candidate sha256')
        path = self.attempts() / digest
        if path.exists():
            return path, json.loads(path.read_text())
        if self.attempts().is_dir():
            for legacy in sorted(self.attempts().iterdir()):
                if legacy.name.startswith('.') or re.fullmatch(r'[0-9a-f]{64}', legacy.name):
                    continue
                details = json.loads(legacy.read_text())
                if not isinstance(details, dict):
                    raise Refused(f'unrecognized Stage 2 attempt record {legacy}')
                if details.get('sha256') == digest:
                    return legacy, details
        return path, None

    def trial_running(self, current):
        """True while this boot is a trial that can still commit.

        The aurora,trial property lasts for the whole boot, but only the spent
        marker lets commit() publish the booted candidate, and commit removes
        it. Without a spent marker a trial boot stages like an ordinary boot.
        An armed marker was written after this boot's commit; the ownership,
        attempt and armed checks apply to it.
        """
        return bool(self.chosen('aurora,trial')) and current is not None and current[0] == 'spent'

    def verify_stage2(self, payload, offset):
        """Traverse the composed FDT records, including the ESP read-back."""
        board = self.board()
        if board is None:
            raise Refused('trial staging requires this Mac\'s live compatible')
        live = self.path('/proc/device-tree/aliases')
        required = [name for name in ('dcp', 'disp0') if (live / name).exists()]
        matched = False
        count = 0
        while payload[offset:offset + 4] == b'\xd0\x0d\xfe\xed':
            header = payload[offset:offset + 40]
            if len(header) != 40:
                raise Refused('truncated Stage 2 DTB header')
            size = int.from_bytes(header[4:8], 'big')
            if size < 40 or offset + size > len(payload):
                raise Refused('invalid Stage 2 DTB size')
            blob = payload[offset:offset + size]
            check = subprocess.run(['dtc', '-I', 'dtb', '-O', 'dtb', '-o', os.devnull],
                                   input=blob, capture_output=True)
            if check.returncode:
                raise Refused('invalid Stage 2 DTB structure')
            with tempfile.NamedTemporaryFile(suffix='.dtb') as stream:
                stream.write(blob)
                stream.flush()
                compatible = subprocess.check_output(
                    ['fdtget', '-t', 's', stream.name, '/', 'compatible'], text=True).split()
                if board in compatible:
                    nodes = dtb_nodes(blob)
                    for alias in required:
                        found = subprocess.run(['fdtget', '-t', 's', stream.name, '/aliases', alias],
                                               capture_output=True, text=True)
                        node = found.stdout.strip()
                        if found.returncode or not node.startswith('/'):
                            raise Refused(f'{board} DTB lacks display alias {alias}')
                        if node not in nodes:
                            raise Refused(f'{board} DTB display alias {alias} has no node')
                    matched = True
            offset += size
            count += 1
        if not matched or not count or payload[offset:offset + 2] != b'\x1f\x8b':
            raise Refused(f'Stage 2 lacks complete DTBs for {board} or compressed U-Boot')

    def armed_trial(self, candidate, receipt, relative):
        """The receipt of an armed trial when this updater armed it, else None."""
        try:
            details = json.loads(receipt.read_text())
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        except (OSError, ValueError):
            return None
        if (not isinstance(details, dict) or details.get('path') != relative
                or details.get('sha256') != digest):
            return None
        _, recorded = self.attempt(digest)
        return details if recorded == details else None

    def withdraw_trial(self, paths, details, reason):
        """Disarm a trial that was never booted. Its candidate may be armed again."""
        _, candidate, receipt, marker, _ = paths
        # Removing the marker disarms it; an interruption after that only
        # leaves an attempt record, which keeps the candidate from rearming.
        marker.unlink()
        sync_dir(marker.parent)
        self.flush_esp()
        attempt, recorded = self.attempt(details['sha256'])
        if recorded == details:
            attempt.unlink()
            sync_dir(attempt.parent)
        receipt.unlink(missing_ok=True)
        candidate.unlink(missing_ok=True)
        sync_dir(candidate.parent)
        self.flush_esp()
        print(f'Stage 2 trial for kernel {details.get("kernel")} withdrawn before it was booted: '
              f'{reason}; live image kept')

    def withdraw_stale_trial(self, selected):
        """The selected Stage 2 is live already, so an armed trial would only replace it."""
        esp = self.env.get('ESP_ROOT')
        if not esp or not (self.path(esp) / 'aura-try').exists():
            return
        try:
            paths = self.trial_paths()
        except Refused as error:
            print(f'update-m1n1: not checking the armed trial: {error}', file=sys.stderr)
            return
        _, candidate, receipt, marker, relative = paths
        if self.marker(marker) != ('armed', relative):
            return
        armed = self.armed_trial(candidate, receipt, relative)
        if armed is None:
            print(f'update-m1n1: leaving the armed trial at {relative}: this updater did not arm it',
                  file=sys.stderr)
            return
        self.withdraw_trial(paths, armed, f'the Stage 2 for kernel {selected} is already live')

    def stage_trial(self, selected, payload):
        paths = self.trial_paths()
        target, candidate, receipt, marker, relative = paths
        current = self.marker(marker)
        if self.trial_running(current):
            raise Refused('a trial is running; preserve its candidate until the next boot')
        if current and current[1] != relative:
            raise Refused('another aura-try owns the ESP marker')
        digest = hashlib.sha256(payload).hexdigest()
        # A trial at a file Stage 1 does not load boots once and commits where nothing reads it.
        unloaded = self.stage1_hold(target)
        hold = unloaded or self.downgrade_hold(payload)
        if current and current[0] == 'armed':
            armed = self.armed_trial(candidate, receipt, relative)
            stale = None
            if armed and armed.get('kernel') != selected:
                # It pairs another kernel's trees with the kernel GRUB boots.
                stale = f'GRUB boots kernel {selected}'
            elif armed and hold:
                # Armed before these checks, or before a newer Stage 2 ran: it never booted.
                stale = unloaded or self.downgrade_hold(candidate.read_bytes())
            if stale:
                self.withdraw_trial(paths, armed, stale)
                current = None
            elif armed and armed['sha256'] == digest:
                print(f'Stage 2 trial for kernel {selected} already armed at {relative}, sha256 {digest}')
                return
        if hold:
            self.keep(hold)
            return
        attempt, recorded = self.attempt(digest)
        # Only a committed candidate may be tried again, e.g. after a package
        # revert. One that fell back or was interrupted is never rearmed.
        if recorded is not None and recorded.get('result') != 'committed':
            print(f'Stage 2 trial already attempted for candidate {digest} '
                  f'(kernel {recorded.get("kernel")}); not rearming')
            return
        attempt = self.attempts() / digest
        if current and current[0] == 'armed':
            raise Refused('a Stage 2 trial is already armed')
        offset = len(self.path(self.env.get('M1N1', '/usr/lib64/m1n1/m1n1.bin')).read_bytes())
        self.verify_stage2(payload, offset)
        if candidate.exists():
            # Keep the previous trial evidence when a newer kernel is staged.
            suffix = hashlib.sha256(candidate.read_bytes()).hexdigest()
            replace_file(target.with_name(target.name + '.failed-' + suffix), candidate.read_bytes())
            if receipt.exists():
                replace_file(target.with_name(target.name + '.failed-' + suffix + '.json'), receipt.read_bytes())
        replace_file(candidate, payload)
        self.verify_stage2(candidate.read_bytes(), offset)
        details = {'kernel': selected, 'path': relative, 'sha256': hashlib.sha256(payload).hexdigest(),
                   'dtb_offset': offset, 'generation': self.selected_generation}
        replace_file(receipt, (json.dumps(details, sort_keys=True) + '\n').encode())
        # Persist before arming. An interrupted update must never automatically
        # grant this kernel another attempt. Marker is always the last write.
        attempt.parent.mkdir(parents=True, exist_ok=True)
        sync_dir(attempt.parent.parent)
        replace_file(attempt, (json.dumps(details, sort_keys=True) + '\n').encode())
        self.flush_esp()
        temporary = marker.with_name(marker.name + '.tmp')
        if temporary.is_symlink():
            raise Refused('aura-try.tmp is a symlink')
        replace_file(temporary, f'armed\n{relative}\n'.encode())
        os.replace(temporary, marker)
        sync_dir(marker.parent)
        self.flush_esp()
        print(f'Stage 2 trial armed for kernel {selected} at {relative}, sha256 {digest}; live image kept')

    def sanity(self):
        source = subprocess.check_output(['findmnt', '-nro', 'SOURCE', '--target', '/'], text=True).strip()
        devices = subprocess.check_output(['lsblk', '-snro', 'KNAME', source.split('[')[0]], text=True).split()
        if not any(re.fullmatch(r'nvme\d+n\d+(?:p\d+)?', name) for name in devices):
            raise Refused('root is not mounted on NVMe')
        deferred = self.path('/sys/kernel/debug/devices_deferred')
        # Absence of debugfs cannot prove that DT-described devices probed.
        for line in deferred.read_text().splitlines():
            if not line.strip():
                continue
            name = line.split()[0]
            if '/' in name or name in ('.', '..'):
                raise Refused('unrecognized deferred device name')
            if any(self.path('/sys/bus').glob(f'*/devices/{name}/of_node')):
                raise Refused(f'DT device still deferred: {name}')
        tree = self.path('/proc/device-tree')
        devices = list(self.path('/sys/bus/platform/devices').glob('*/of_node'))
        for compatible in tree.rglob('compatible'):
            values = compatible.read_bytes().split(b'\0')
            if not any(re.fullmatch(rb'apple,(?:[a-z0-9]+-)?dcp(?:ext)?', value) for value in values):
                continue
            node = compatible.parent
            ancestors = [node] + list(node.parents)[:len(node.relative_to(tree).parts) - 1]
            if any((p / 'status').exists() and (p / 'status').read_bytes().rstrip(b'\0')
                   not in (b'ok', b'okay') for p in ancestors):
                continue
            bound = [p for p in devices if p.resolve() == node.resolve()]
            if not bound or not all((p.parent / 'driver').is_dir() for p in bound):
                raise Refused(f'DCP is not bound: {node.relative_to(tree)}')

    def guard(self):
        # Keep the one-shot fallback even if Linux feeds the hardware watchdog
        # but never reaches the commit service or fails its DT checks.
        _, _, _, marker, relative = self.trial_paths()
        if self.chosen('aurora,trial') == relative and self.marker(marker) == ('spent', relative):
            print(f'aurora-stage2-guard: trial {relative} was not committed; rebooting to the configured Stage 2', flush=True)
            subprocess.run(['systemctl', '--no-block', 'reboot'], check=True)

    def commit(self):
        target, candidate, receipt, marker, relative = self.trial_paths()
        current = self.marker(marker)
        trial = self.chosen('aurora,trial')
        if not current:
            return
        if current[1] != relative:
            # A trial armed by hand with aura-try (or by another tool) is not
            # this updater's to commit: leave its marker and image alone.
            print(f'aurora-stage2-commit: the aura-try marker names {current[1]}, not {relative}; '
                  'that trial is not managed here, nothing to commit')
            return
        if current[0] == 'spent' and not trial:
            print(f'aurora-stage2-commit: trial {relative} fell back; live Stage 2 kept, candidate left for inspection')
            return
        if current != ('spent', relative) or trial != relative:
            return
        details = json.loads(receipt.read_text())
        self.validate_version(details['kernel'])
        attempt, recorded = self.attempt(details['sha256'])
        if recorded != details or details['path'] != relative:
            raise Refused('trial receipt does not match its recorded attempt')
        payload = candidate.read_bytes()
        if hashlib.sha256(payload).hexdigest() != details['sha256']:
            raise Refused('trial candidate changed since it was armed')
        self.verify_stage2(payload, details['dtb_offset'])
        older = [version for version in self.kernel_images()
                 if self.generation(version) < details['generation']]
        if older:
            raise Refused('retained kernels now require an older DT ABI generation: ' + ', '.join(sorted(older)))
        self.sanity()
        previous = target.read_bytes()
        replace_file(target.with_name(target.name + '.prev'), previous)
        self.flush_esp()
        try:
            # Same-directory rename publishes exactly the verified trial file.
            os.replace(candidate, target)
            sync_dir(target.parent)
            self.flush_esp()
            if hashlib.sha256(target.read_bytes()).hexdigest() != details['sha256']:
                raise Refused('committed Stage 2 read-back sha256 mismatch')
        except (OSError, Refused, subprocess.SubprocessError):
            if not candidate.exists():
                replace_file(candidate, payload)
            replace_file(target, previous)
            self.flush_esp()
            raise
        marker.unlink()
        sync_dir(marker.parent)
        self.flush_esp()
        print(f'aurora-stage2-commit: committed {relative}, sha256 {details["sha256"]}; backup {target.name}.prev')
        # The marker removal above is the commit. Recording the result lets a
        # later update try this exact candidate again; failing to record it
        # only keeps that candidate from another automatic trial.
        try:
            committed = self.attempts() / details['sha256']
            replace_file(committed, (json.dumps(dict(details, result='committed'), sort_keys=True) + '\n').encode())
            if attempt != committed:
                attempt.unlink()
                sync_dir(attempt.parent)
        except OSError as error:
            print(f'aurora-stage2-commit: could not record the committed attempt: {error}')

    def sign(self, payload):
        """Hand the composed Stage 2 to aurora-secboot ("stage2 hook"), which signs it with the
        owner's Stage 2 key when Stage 2 signing is on and returns it unchanged otherwise. A Stage 1
        that enforces signatures refuses an unsigned Stage 2, so a failure keeps the last one."""
        signer = self.path(self.env.get('AURORA_STAGE2_SIGNER', '/usr/bin/aurora-secboot'))
        if not signer.is_file():
            return payload
        with tempfile.TemporaryDirectory(prefix='aurora-stage2-sign.') as work:
            source, signed = Path(work) / 'stage2', Path(work) / 'stage2.signed'
            source.write_bytes(payload)
            result = subprocess.run([str(signer), 'stage2', 'hook', str(source), str(signed)],
                                    capture_output=True, text=True)
            if result.returncode:
                detail = (result.stderr or result.stdout).strip().splitlines()
                raise Refused('Stage 2 signing failed: ' + (detail[-1] if detail else f'exit {result.returncode}'))
            output = signed.read_bytes()
        # Signing only appends a trailer; the composed image itself stays as built.
        if output[:len(payload)] != payload:
            raise Refused('the Stage 2 signer changed the composed image')
        if self.ctxr_board() and len(output) > 16 * 1024 * 1024:
            raise Refused('signed CTXR Stage 2 exceeds the 16 MiB slot; keeping the working images')
        for line in result.stdout.splitlines():
            print(line)
        return output

    def apply(self):
        selected, source, own, payload = self.plan()
        payload = self.sign(payload)
        target = self.target()
        if target.is_symlink():
            raise Refused('Stage 2 target is a symlink')
        # Make the versioned boot DTB directory complete before exposing it.
        destination = self.path(f'/boot/dtb-{selected}')
        if destination.exists():
            if self.tree(destination) != own:
                raise Refused(f'{destination} differs from the installed kernel DTBs')
        else:
            staged = Path(tempfile.mkdtemp(prefix='.dtb-', dir=self.path('/boot')))
            try:
                for p in source.iterdir():
                    if p.is_dir():
                        shutil.copytree(p, staged / p.name)
                    else:
                        shutil.copy2(p, staged / p.name)
                for p in staged.rglob('*'):
                    if p.is_file():
                        with p.open('rb') as stream:
                            os.fsync(stream.fileno())
                for p in sorted((p for p in staged.rglob('*') if p.is_dir()), reverse=True):
                    sync_dir(p)
                sync_dir(staged)
                os.rename(staged, destination)
                sync_dir(destination.parent)
            finally:
                if staged.exists():
                    shutil.rmtree(staged)
        previous = target.read_bytes() if target.exists() else None
        if previous is not None and self.supports_trial():
            if previous != payload:
                self.stage_trial(selected, payload)
            else:
                self.withdraw_stale_trial(selected)
        elif previous != payload and (hold := self.stage2_hold(target, payload)):
            self.keep(hold)
        elif previous != payload:
            # Finish and sync the candidate before changing even the backup.
            fd, name = tempfile.mkstemp(prefix='.boot.bin.', dir=target.parent)
            staged = Path(name)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fchmod(stream.fileno(), 0o644)
                    os.fsync(stream.fileno())
                if staged.read_bytes() != payload:
                    raise Refused('Stage 2 read-back failed')
                if previous is not None:
                    replace_file(target.with_name(target.name + '.old'), previous)
                os.replace(staged, target)
                sync_dir(target.parent)
            finally:
                staged.unlink(missing_ok=True)
        link = self.path('/boot/dtb')
        if self.env.get('AURORA_FIRMWARE_DT') == 'True':
            # Preserve grubby's firmware-DT policy, but defer link removal
            # until the complete Stage 2 has been durably staged.
            if link.is_symlink():
                link.unlink()
                sync_dir(link.parent)
            print(f'Stage 2 {"left unchanged" if self.held else "verified"} at {target}; firmware DT policy retained')
            return
        if not link.is_symlink() or os.readlink(link) != destination.name:
            fd, name = tempfile.mkstemp(prefix='.dtb-link-', dir=link.parent)
            os.close(fd)
            temporary = Path(name)
            temporary.unlink()
            try:
                temporary.symlink_to(destination.name)
                os.replace(temporary, link)
                sync_dir(link.parent)
            finally:
                temporary.unlink(missing_ok=True)
        print(f'Stage 2 {"left unchanged" if self.held else "verified"} at {target}; /boot/dtb -> {destination.name}')

    def drop_removed_link(self):
        link = self.path('/boot/dtb')
        if link.is_symlink() and os.readlink(link) in (
                f'dtb-{self.version}', f'/boot/dtb-{self.version}'):
            link.unlink()
            sync_dir(link.parent)

    def cleanup_remove(self):
        if self.action != 'remove':
            raise Refused('erase cleanup requires a remove action')
        self.drop_removed_link()
        print('Stage 2 refresh deferred; continuing removal of the erased kernel boot files')

    # A removal inside a package transaction cannot tell what GRUB boots next:
    # the transaction may add kernels after it, the removed one too when it is
    # reinstalled. It leaves Stage 2 to their add phases and to a refresh once
    # the transaction ends, both run from RPM file triggers.

    def transaction_record(self):
        return self.path('/run/update-m1n1/transaction')

    def process_start(self, pid):
        """A running process's start time, which tells it from a later one with its pid."""
        try:
            fields = self.path(f'/proc/{int(pid)}/stat').read_text().rpartition(')')[2].split()
        except (OSError, ValueError):
            return None
        return fields[19] if len(fields) > 19 else None

    def begin_transaction(self):
        """Record the package transaction that is about to remove kernels."""
        pid = self.env.get('AURORA_RPM_TRANSACTION_PID', '')
        start = self.process_start(pid) if re.fullmatch(r'[1-9][0-9]*', pid) and pid != '1' else None
        if start is None:
            print('update-m1n1: no package transaction process; kernel removals update Stage 2 at once',
                  file=sys.stderr)
            return
        record = self.transaction_record()
        record.parent.mkdir(parents=True, exist_ok=True)
        replace_file(record, (json.dumps({'pid': int(pid), 'start': start, 'deferred': []}) + '\n').encode())

    def transaction(self):
        """The running package transaction's record, or None. A stale one is dropped."""
        path = self.transaction_record()
        try:
            record = json.loads(path.read_text())
            live = (isinstance(record, dict) and isinstance(record.get('deferred'), list)
                    and record.get('start') is not None
                    and self.process_start(record.get('pid')) == record['start'])
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError):
            live = False
        if not live:
            path.unlink(missing_ok=True)
            return None
        return record

    def defer_remove(self):
        """Inside a package transaction, leave this removal's Stage 2 to the transaction."""
        if self.action != 'remove':
            raise Refused('deferring requires a remove action')
        record = self.transaction()
        if record is None:
            return False
        # kernel-install removes /boot/dtb-<version> next.
        self.drop_removed_link()
        if self.version not in record['deferred']:
            record['deferred'].append(self.version)
        replace_file(self.transaction_record(), (json.dumps(record) + '\n').encode())
        print(f'update-m1n1: kernel {self.version} removed inside a package transaction; '
              'Stage 2 follows the kernels it adds and what GRUB boots after it')
        return True

    def end_transaction(self):
        """Drop the transaction record. True when its removals left Stage 2 to now."""
        path = self.transaction_record()
        try:
            record = json.loads(path.read_text())
            due = bool(record['deferred'])
        except FileNotFoundError:
            return False
        except (OSError, ValueError, TypeError, KeyError):
            due = True  # Unreadable: a refresh is always safe.
        path.unlink(missing_ok=True)
        return due


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--commit', action='store_true')
    parser.add_argument('--guard', action='store_true')
    parser.add_argument('--cleanup-remove', action='store_true')
    # Exit 0 when the removal was left to the running package transaction.
    parser.add_argument('--defer-remove', action='store_true')
    parser.add_argument('--transaction-begin', action='store_true')
    # Exit 0 when removals in the finished transaction left Stage 2 to a refresh.
    parser.add_argument('--transaction-end', action='store_true')
    args = parser.parse_args()
    try:
        update = Update()
        if args.guard:
            update.guard()
        elif args.commit:
            update.commit()
        elif args.cleanup_remove:
            update.cleanup_remove()
        elif args.defer_remove:
            return 0 if update.defer_remove() else 1
        elif args.transaction_begin:
            update.begin_transaction()
        elif args.transaction_end:
            return 0 if update.end_transaction() else 1
        elif args.check:
            update.plan()
        else:
            update.apply()
    except (Refused, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'update-m1n1: {error}; keeping the last complete Stage 2 and trial evidence', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
