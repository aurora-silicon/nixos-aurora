#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fail an Aurora image build that lacks the basics every image must have.

Checked against the finished root (and, with --esp, the EFI and boot
filesystems the installer writes):

  locale     a UTF-8 default (/etc/locale.conf) that is actually generated
  terminal   desktops ship their terminal and its launcher
  wallpaper  GNOME's backgrounds and default picture; Plasma's wallpapers
  boot       GRUB finds /boot by filesystem UUID on the startup disk only:
             no partition number in the core, no lookup without a hint
  network    NetworkManager is enabled; desktops ship its settings UI
  lid        logind still suspends on lid close; sleep is not masked
  GL         factory images leave Mesa driver selection automatic

--system names a NixOS system closure; its software and /etc are read
from there instead of /usr and /etc.
"""
import argparse
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

PREAMBLE = 'Aurora: look for this installation only on the disk GRUB started from.'
IMAGE_SUFFIXES = ('.jpg', '.jpeg', '.png', '.jxl', '.svg', '.webp', '.avif')
TERMINALS = {
    'gnome': [('kgx', 'org.gnome.Console.desktop'), ('gnome-terminal', 'org.gnome.Terminal.desktop'),
              ('ptyxis', 'org.gnome.Ptyxis.desktop')],
    'kde': [('konsole', 'org.kde.konsole.desktop')],
}


class Root:
    """Paths inside an image root; absolute symbolic links stay inside it."""

    def __init__(self, root, system=None):
        self.root = Path(root)
        self.system = system
        self.usr = f'{system}/sw' if system else '/usr'
        self.etc = f'{system}/etc' if system else '/etc'

    def path(self, name, depth=0):
        if depth > 40:
            raise RuntimeError(f'too many symbolic links: {name}')
        current = self.root
        parts = PurePosixPath(name).parts[1:]
        for index, part in enumerate(parts):
            candidate = current / part
            if candidate.is_symlink():
                target = os.readlink(candidate)
                rest = '/'.join(parts[index + 1:])
                if target.startswith('/'):
                    joined = target + ('/' + rest if rest else '')
                else:
                    inside = '/' + str(current.relative_to(self.root)) if current != self.root else ''
                    joined = os.path.normpath(f'{inside}/{target}') + ('/' + rest if rest else '')
                return self.path(joined, depth + 1)
            current = candidate
        return current

    def text(self, name):
        path = self.path(name)
        return path.read_text(errors='replace') if path.is_file() else None


def normalize_locale(name):
    language, _, codeset = name.partition('.')
    codeset, _, modifier = codeset.partition('@')
    codeset = re.sub(r'[^0-9a-z]', '', codeset.lower())
    return f'{language}.{codeset}' + (f'@{modifier}' if modifier else '')


def assignments(text):
    values = {}
    for line in (text or '').splitlines():
        line = line.strip()
        if line.startswith('export '):
            line = line[7:]
        if '=' in line and not line.startswith('#'):
            key, _, value = line.partition('=')
            values[key.strip()] = value.strip().strip('"\'')
    return values


def check_gl_selection(root):
    """Factory images leave GL selection to Mesa; fallback is per application."""
    files = [f'{root.etc}/environment', f'{root.etc}/set-environment',
             f'{root.etc}/pam/environment']
    for directory in (f'{root.etc}/environment.d', f'{root.usr}/lib/environment.d'):
        path = root.path(directory)
        if path.is_dir():
            files.extend(f'{directory}/{p.name}' for p in sorted(path.glob('*.conf')))
    for file in files:
        for line in (root.text(file) or '').splitlines():
            values = assignments(line)
            for key in ('MESA_LOADER_DRIVER_OVERRIDE', 'GALLIUM_DRIVER'):
                if values.get(key):
                    return f'global {key} in {file}; leave factory GL selection automatic'
    return None


def check_locale(root):
    lang = assignments(root.text(f'{root.etc}/locale.conf')).get('LANG', '')
    if not re.search(r'\.(utf-?8)(@|$)', lang, re.IGNORECASE):
        return f'no UTF-8 default locale: /etc/locale.conf has LANG={lang or "(unset)"}'
    name = normalize_locale(lang)
    if name == 'C.utf8':
        return None
    archives = [f'{root.usr}/lib/locale/locale-archive']
    if root.system:
        # NixOS points LOCALE_ARCHIVE at i18n.glibcLocales.
        for file in ('set-environment', 'profile', 'pam/environment'):
            for archive in re.findall(r'LOCALE_ARCHIVE\b[^\n]*?(/nix/store/[^"\'\s]+/locale-archive)',
                                      root.text(f'{root.etc}/{file}') or ''):
                archives.insert(0, archive)
    elif root.path(f'/usr/lib/locale/{name}/LC_CTYPE').is_file():
        return None
    for archive in archives:
        path = root.path(archive)
        if path.is_file() and (name.encode() + b'\0') in path.read_bytes():
            return None
    return f'the default locale {lang} is not generated'


def check_terminal(root, profile):
    for binary, launcher in TERMINALS[profile]:
        if (root.path(f'{root.usr}/bin/{binary}').exists()
                and root.path(f'{root.usr}/share/applications/{launcher}').is_file()):
            return None
    names = ', '.join(binary for binary, _ in TERMINALS[profile])
    return f'no terminal with a launcher ({names})'


def images(directory):
    if not directory.is_dir():
        return []
    return [path for path in directory.rglob('*') if path.suffix.lower() in IMAGE_SUFFIXES]


def gnome_default_picture(root):
    """The effective org.gnome.desktop.background picture-uri, if it can be read."""
    schemas = root.path(f'{root.usr}/share/glib-2.0/schemas')
    if not schemas.is_dir():
        return None
    value = None
    schema = schemas / 'org.gnome.desktop.background.gschema.xml'
    if schema.is_file():
        found = re.search(r'<key name="picture-uri"[^>]*>.*?<default>\s*\'([^\']*)\'', schema.read_text(), re.S)
        value = found and found[1]
    # Vendor overrides apply in file-name order; later files win.
    for override in sorted(schemas.glob('*.gschema.override')):
        section = None
        for line in override.read_text(errors='replace').splitlines():
            line = line.strip()
            if line.startswith('['):
                section = line.strip('[]').strip()
            elif section == 'org.gnome.desktop.background' and line.startswith('picture-uri'):
                found = re.search(r"=\s*'([^']*)'", line)
                if found:
                    value = found[1]
    return value


def check_wallpaper(root, profile):
    if profile == 'gnome':
        if not images(root.path(f'{root.usr}/share/backgrounds/gnome')):
            return "GNOME's backgrounds (gnome-backgrounds) are missing"
        if not root.system:
            uri = gnome_default_picture(root)
            if not uri:
                return 'the GNOME background schema has no default picture'
            if uri.startswith('file://') and not root.path(uri[7:]).is_file():
                return f'the default GNOME background {uri} does not exist'
    else:
        wallpapers = root.path(f'{root.usr}/share/wallpapers')
        packages = [entry for entry in wallpapers.iterdir() if images(entry / 'contents/images')] \
            if wallpapers.is_dir() else []
        # plasma-workspace ships only its default (Next) and a couple more;
        # plasma-workspace-wallpapers adds two dozen.
        if len(packages) < 8:
            return "Plasma's wallpapers (plasma-workspace-wallpapers) are missing"
    return None


def check_network(root, profile):
    unit = root.path(f'{root.etc}/systemd/system/multi-user.target.wants') / 'NetworkManager.service'
    if not (unit.is_symlink() or unit.exists()):
        return 'NetworkManager.service is not enabled'
    if profile == 'gnome' and not root.path(f'{root.usr}/bin/gnome-control-center').exists():
        return 'GNOME Settings (network and Wi-Fi) is missing'
    # plasma-nm: its System Settings module, and the panel applet (a plugin
    # since Plasma 6.8, a package directory before).
    if profile == 'kde' and not (
            root.path(f'{root.usr}/share/applications/kcm_networkmanagement.desktop').is_file()
            or root.path(f'{root.usr}/share/plasma/plasmoids/org.kde.plasma.networkmanagement').is_dir()):
        return "Plasma's network settings (plasma-nm) are missing"
    return None


def check_lid(root):
    files = [root.path(f'{root.etc}/systemd/logind.conf')]
    for directory in (f'{root.etc}/systemd/logind.conf.d', '/usr/lib/systemd/logind.conf.d',
                      f'{root.usr}/lib/systemd/logind.conf.d'):
        path = root.path(directory)
        if path.is_dir():
            files += sorted(path.glob('*.conf'))
    for path in files:
        if not path.is_file():
            continue
        for line in path.read_text(errors='replace').splitlines():
            found = re.match(r'\s*HandleLidSwitch\s*=\s*(\S+)', line)
            if found and found[1] != 'suspend':
                return f'{path.name} sets HandleLidSwitch={found[1]}'
    units = root.path(f'{root.etc}/systemd/system')
    for unit in ('sleep.target', 'suspend.target', 'systemd-suspend.service', 'systemd-logind.service'):
        path = units / unit
        if path.is_symlink() and os.readlink(path) == '/dev/null':
            return f'{unit} is masked'
    return None


def boot_reader(args):
    if args.boot_dir:
        base = Path(args.boot_dir)
        return lambda name: (base / name).read_bytes() if (base / name).is_file() else None

    def read(name):
        # debugfs exits 0 either way; a missing file is reported on stderr.
        result = subprocess.run(['debugfs', '-R', f'cat /{name}', args.boot_image],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0 or b'not found' in result.stderr.lower():
            return None
        return result.stdout
    return read


def unhinted_searches(text):
    return [line.strip() for line in text.splitlines()
            if re.match(r'\s*search\b', line) and ('--hint' not in line or '--no-floppy' not in line)]


def check_boot(args):
    esp, uuid = Path(args.esp), args.boot_uuid.lower()
    read = boot_reader(args)
    grub = 'grub2' if args.grub_flavor == 'fedora' else 'grub'
    if args.grub_flavor == 'fedora':
        stubs = [path for path in sorted(esp.glob('EFI/*/grub.cfg')) if 'configfile' in path.read_text()]
        if read(f'{grub}/aurora-boot-{uuid}') is None:
            return f'the /boot marker {grub}/aurora-boot-{uuid} is missing'
    else:
        core = esp / 'EFI/BOOT/BOOTAA64.EFI'
        if not core.is_file():
            return 'EFI/BOOT/BOOTAA64.EFI is missing'
        data = core.read_bytes()
        # grub-install embeds either a partition number or an early
        # "search.fs_uuid <boot>" that falls back to every disk; Aurora's core
        # embeds neither and runs EFI/BOOT/grub.cfg instead.
        if re.search(rb'\((hd\d+)?,gpt\d+\)', data) or uuid.encode() in data.lower():
            return 'the GRUB core names /boot by partition number or by an all-disk search'
        if b'/EFI/BOOT' not in data:
            return 'the GRUB core does not load its configuration from EFI/BOOT'
        stubs = [esp / 'EFI/BOOT/grub.cfg']
    if not stubs or not all(path.is_file() for path in stubs):
        return 'the EFI GRUB stub configuration is missing'
    for path in stubs:
        text = path.read_text()
        if PREAMBLE not in text or uuid not in text.lower():
            return f'{path.relative_to(esp)} does not find /boot ({uuid}) by UUID on the startup disk'
        if unhinted_searches(text):
            return f'{path.relative_to(esp)} has a lookup without a hint: {unhinted_searches(text)[0]}'
    main = read(f'{grub}/grub.cfg')
    if main is None:
        return f'/boot/{grub}/grub.cfg is missing'
    if unhinted_searches(main.decode(errors='replace')):
        return f'/boot/{grub}/grub.cfg has a lookup without a hint: {unhinted_searches(main.decode())[0]}'
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--profile', required=True, choices=['kde', 'gnome', 'minimal'])
    parser.add_argument('--root', help='the finished image root')
    parser.add_argument('--system', help='NixOS: the system closure installed in the root')
    parser.add_argument('--esp', help='the EFI partition contents')
    parser.add_argument('--boot-dir', help='the /boot filesystem contents')
    parser.add_argument('--boot-image', help='the /boot filesystem image (ext4)')
    parser.add_argument('--boot-uuid', help='the /boot filesystem UUID')
    parser.add_argument('--grub-flavor', choices=['arch', 'fedora'], default='arch')
    args = parser.parse_args()
    if not args.root and not args.esp:
        parser.error('nothing to check: give --root, --esp or both')
    if args.esp and not (args.boot_uuid and (args.boot_dir or args.boot_image)):
        parser.error('--esp needs --boot-uuid and --boot-dir or --boot-image')
    checks = []
    if args.root:
        root = Root(args.root, args.system)
        checks.append(('locale', check_locale(root)))
        checks.append(('gl-selection', check_gl_selection(root)))
        if args.profile != 'minimal':
            checks.append(('terminal', check_terminal(root, args.profile)))
            checks.append(('wallpaper', check_wallpaper(root, args.profile)))
        checks.append(('network', check_network(root, args.profile)))
        checks.append(('lid', check_lid(root)))
    if args.esp:
        checks.append(('boot', check_boot(args)))
    failures = [(name, problem) for name, problem in checks if problem]
    for name, problem in checks:
        print(f'aurora basics: {name}: {"FAIL: " + problem if problem else "ok"}')
    if failures:
        print('aurora basics: this image is missing basics every Aurora image must have', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
