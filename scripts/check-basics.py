#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fail an Aurora image build that lacks the basics every image must have.

Checked against the finished root (and, with --esp, the EFI and boot
filesystems the installer writes):

  locale     a UTF-8 default (/etc/locale.conf) that is actually generated
  terminal   desktops ship their terminal and its launcher
  wallpaper  GNOME's backgrounds and default picture; Plasma's wallpapers
  boot       GRUB finds /boot by filesystem UUID on the startup disk only:
             no partition number in the core, no lookup without a hint;
             every module, font, file and filesystem UUID its
             configurations name is in the image
  network    NetworkManager is enabled; desktops ship its settings UI
  usb4       bolt authorizes USB4 and Thunderbolt devices: boltctl, an
             unmasked bolt.service and the udev rule that starts it; KDE
             ships its Thunderbolt settings (GNOME Settings has them)
  lid        logind still suspends on lid close; sleep is not masked
  touchid    sudo, polkit and the lock screen offer a fingerprint, the login
             screen, the console login, su and ssh ask for the password;
             a short press of the power button suspends
  GL         factory images leave Mesa driver selection automatic
  greeter    KDE signs in with Plasma Login, whose greeter runs on KWin
             Wayland at the display's scale (SDDM's Xorg greeter drew at 1x)

--system names a NixOS system closure; its software and /etc are read
from there instead of /usr and /etc.
"""
import argparse
import os
from pathlib import Path, PurePosixPath
import re
import struct
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


def bolt_udev_rule(text):
    """Whether a udev rules file starts bolt.service for Thunderbolt devices."""
    for line in text.replace('\\\n', ' ').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if (re.search(r'(?:^|[\s,])SUBSYSTEM\s*==\s*"thunderbolt"', line)
                and re.search(r'(?:^|[\s,])ENV\{SYSTEMD_WANTS\}\s*\+?=\s*"(?:[^"]*\s)?bolt\.service(?:\s[^"]*)?"', line)):
            return True
    return False


def check_usb4(root, profile):
    # A USB4 or Thunderbolt domain at security level "user" builds a PCIe
    # tunnel only once userspace authorizes the device; bolt does that. Its
    # udev rule starts boltd at the first Thunderbolt device. udev reads a
    # rule in /etc over the one of the same name in /usr/lib.
    if not root.path(f'{root.usr}/bin/boltctl').is_file():
        return 'bolt is missing: nothing authorizes USB4 and Thunderbolt devices'
    units = (f'{root.usr}/lib/systemd/system', f'{root.etc}/systemd/system')
    unit = root.path(units[1]) / 'bolt.service'
    if unit.is_symlink() and os.readlink(unit) == '/dev/null':
        return 'bolt.service is masked'
    if not any(root.path(f'{directory}/bolt.service').is_file() for directory in units):
        return 'bolt.service is missing'
    rules = {}
    for directory in (f'{root.usr}/lib/udev/rules.d', f'{root.etc}/udev/rules.d'):
        if root.path(directory).is_dir():
            for entry in root.path(directory).iterdir():
                if entry.name.endswith('.rules'):
                    rules[entry.name] = root.path(f'{directory}/{entry.name}')
    if not any(path.is_file() and bolt_udev_rule(path.read_text(errors='replace'))
               for path in rules.values()):
        return 'no udev rule starts bolt.service for Thunderbolt devices'
    # plasma-thunderbolt: the new-device notification and the System Settings page.
    if profile == 'kde' and not root.path(f'{root.usr}/share/knotifications6/kded_bolt.notifyrc').is_file():
        return "Plasma's Thunderbolt settings (plasma-thunderbolt) are missing"
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


def check_greeter(root, profile):
    if profile != 'kde':
        return None
    # systemctl enable links the display manager's Alias=; NixOS links its
    # aliases= the same way. Either resolves to the unit file itself.
    unit = root.path(f'{root.etc}/systemd/system/display-manager.service')
    if not unit.is_file():
        return 'no display manager is enabled (display-manager.service)'
    if unit.name != 'plasmalogin.service':
        return f'the display manager is {unit.name}, not Plasma Login (plasmalogin.service)'
    return None


# Touch ID: where PAM offers a fingerprint, and what the power button does.
FINGERPRINT_SERVICES = ('sudo', 'polkit-1')
PASSWORD_SERVICES = ('login', 'su', 'su-l', 'sshd')
LOCK_SCREENS = {'gnome': ('gdm-fingerprint',), 'kde': ('kde-fingerprint',)}
# The login screen and the lock screen's password prompt.
PASSWORD_PROMPTS = {'gnome': ('gdm-password',), 'kde': ('plasmalogin', 'kde')}
PAM_ACTIONS = {
    'required': {'success': 'ok', 'default': 'bad'},
    'requisite': {'success': 'ok', 'default': 'die'},
    'sufficient': {'success': 'done', 'default': 'ignore'},
    'optional': {'success': 'ok', 'default': 'ignore'},
}


def pam_auth_rows(text):
    rows = []
    for line in text.replace('\\\n', ' ').splitlines():
        line = line.split('#', 1)[0].strip()
        if line.startswith('@include'):
            rows.append(('include', line.split()[1], []))
            continue
        found = re.match(r'-?auth\s+(\[[^\]]*\]|\S+)\s+(\S+)\s*(.*)', line)
        if found:
            rows.append((found[1], found[2], found[3].split()))
    return rows


def pam_service(root, name):
    """The text of a PAM service as Linux-PAM finds it."""
    if name.startswith('/'):
        return root.text(name)
    for directory in (f'{root.etc}/pam.d', '/usr/lib/pam.d'):
        path = root.path(f'{directory}/{name}')
        if path.is_file():
            return path.read_text(errors='replace')
    return None


def pam_entries(root, name, depth=0):
    text = pam_service(root, name)
    if text is None or depth > 20:
        return None
    entries = []
    for control, module, args in pam_auth_rows(text):
        if control == 'include':
            entries += pam_entries(root, module, depth + 1) or []
        elif control == 'substack':
            entries.append(('substack', pam_entries(root, module, depth + 1) or [], []))
        else:
            entries.append((control, module, args))
    return entries


def succeed_if_service(args, service):
    """pam_succeed_if's answer for a test of the service name, else None."""
    words = [arg for arg in args if arg not in ('quiet', 'quiet_fail', 'quiet_success', 'use_uid', 'debug', 'audit')]
    if len(words) != 3 or words[0] != 'service':
        return None
    op, value = words[1], words[2]
    return {'in': service in value.split(':'), 'notin': service not in value.split(':'),
            '=': service == value, '!=': service != value}.get(op)


def pam_paths(entries, service):
    """Every sequence of modules an authentication can run."""
    paths = []

    def run(index, seen):
        if index >= len(entries):
            paths.append(seen)
            return
        control, module, args = entries[index]
        if control == 'substack':
            for sub in pam_paths(module, service):
                run(index + 1, seen + sub)
            return
        name = os.path.basename(module)
        outcomes = [True, False]
        if name == 'pam_succeed_if.so' and succeed_if_service(args, service) is not None:
            outcomes = [succeed_if_service(args, service)]
        elif name == 'pam_permit.so':
            outcomes = [True]
        elif name in ('pam_deny.so', 'pam_debug.so'):
            outcomes = [False]
        actions = PAM_ACTIONS.get(control) or dict(item.split('=', 1) for item in control.strip('[]').split() if '=' in item)
        for ok in outcomes:
            action = actions.get('success' if ok else 'default', actions.get('default', 'ignore'))
            if action in ('done', 'die'):
                paths.append(seen + (name,))
            elif action.isdigit():
                run(index + 1 + int(action), seen + (name,))
            else:
                run(index + 1, seen + (name,))
    run(0, ())
    return paths


def pam_flat(entries):
    for control, module, args in entries:
        if control == 'substack':
            yield from pam_flat(module)
        else:
            yield control, module, args


def pam_fingerprint(root, service):
    """None when the service is absent, else (fingerprint offered, password after it).

    The password only stays usable when a failed or absent fingerprint moves on:
    pam_fprintd must be sufficient (or a [...] control that ignores failure).
    """
    entries = pam_entries(root, service)
    if entries is None:
        return None
    paths = pam_paths(entries, service)
    offered = [path for path in paths if 'pam_fprintd.so' in path]
    controls = [control for control, module, _ in pam_flat(entries) if os.path.basename(module) == 'pam_fprintd.so']
    tolerant = all(control == 'sufficient' or (control.startswith('[') and
                   dict(item.split('=', 1) for item in control.strip('[]').split() if '=' in item).get('default') == 'ignore')
                   for control in controls)
    fallback = tolerant and any('pam_unix.so' in path[path.index('pam_fprintd.so'):] for path in offered)
    return bool(offered), fallback


def config_value(texts, section, key):
    value = None
    for text in texts:
        current = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith('['):
                current = line
            elif current == section and re.match(rf'{key}\s*=', line):
                value = line.split('=', 1)[1].strip()
    return value


def logind_texts(root):
    files = [root.path(f'{root.etc}/systemd/logind.conf'), root.path('/usr/lib/systemd/logind.conf'),
             root.path(f'{root.usr}/lib/systemd/logind.conf')]
    dropins = {}
    for directory in ('/usr/lib/systemd/logind.conf.d', f'{root.usr}/lib/systemd/logind.conf.d',
                      f'{root.etc}/systemd/logind.conf.d'):
        path = root.path(directory)
        if path.is_dir():
            for item in path.glob('*.conf'):
                dropins[item.name] = item
    texts = [path.read_text(errors='replace') for path in dict.fromkeys(files) if path.is_file()]
    return texts + [dropins[name].read_text(errors='replace') for name in sorted(dropins) if dropins[name].is_file()]


def check_touchid(root, profile):
    problems = []
    expect = [(name, True) for name in FINGERPRINT_SERVICES + LOCK_SCREENS.get(profile, ())]
    expect += [(name, False) for name in PASSWORD_SERVICES + PASSWORD_PROMPTS.get(profile, ())]
    for name, wanted in expect:
        result = pam_fingerprint(root, name)
        if result is None:
            if wanted or name == 'login':
                problems.append(f'PAM service {name} is missing')
            continue
        offered, fallback = result
        if offered != wanted:
            problems.append(f'{name} {"does not offer" if wanted else "offers"} a fingerprint')
        elif wanted and name in FINGERPRINT_SERVICES and not fallback:
            problems.append(f'{name} has no password after the fingerprint')
    logind = logind_texts(root)
    for key, wanted in (('HandlePowerKey', 'suspend'), ('HandlePowerKeyLongPress', 'poweroff')):
        value = config_value(logind, '[Login]', key)
        if value != wanted:
            problems.append(f'logind {key}={value or "(default)"}, not {wanted}')
    if profile == 'kde':
        texts = [root.text(f'{root.etc}/xdg/powerdevilrc') or '']
        for group in ('AC', 'Battery', 'LowBattery'):
            value = config_value(texts, f'[{group}][SuspendAndShutdown]', 'PowerButtonAction')
            if value != '1':
                problems.append(f'Plasma {group} power button action is {value or "the logout screen"}, not suspend')
    return '; '.join(problems) or None


# GRUB references: every module, font and file a GRUB configuration names
# must be where GRUB looks for it on an Apple silicon Mac (arm64-efi), and
# every filesystem UUID it searches for must be in the image. A missing one
# prints "error: ... not found." or "no such device" on the screen at boot.
#
# The configuration is read as the image's first boot runs it: GRUB's own
# variables, the image's grubenv once load_env reads it, and unset variables
# empty. A value only GRUB knows when it runs (regexp or probe results, a
# search by label or file, $cmdpath) is unknown, and a reference that needs
# one fails closed: "cannot resolve" unless an enclosing [ -f/-e/-s/-d PATH ]
# tests that path first. Branches that cannot run on arm64-efi are skipped;
# a command used as a condition is still checked, since GRUB only hides its
# error. menuentry, submenu and function bodies run after the configuration
# in a copy of its variables; source and configfile targets are read too.
GRUB_TARGET = 'arm64-efi'
# Normal mode sets these to "y" (grub-core/normal/main.c, GRUB 2.02 and later).
GRUB_FEATURES = ('feature_chainloader_bpb', 'feature_ntldr', 'feature_platform_search_hint',
                 'feature_default_font_path', 'feature_all_video_module', 'feature_menuentry_id',
                 'feature_menuentry_options', 'feature_200_final', 'feature_nativedisk_cmd',
                 'feature_timeout_style')
# Set by GRUB while it runs; never known to this check.
GRUB_RUNTIME = ('cmdpath', 'fw_path', 'chosen')
GRUB_PROBES = {'-f', '-e', '-s', '-d'}
GRUB_BLOCKS = ('menuentry', 'submenu', 'function')
GRUB_DEPTH = 8
GRUB_UNKNOWN = None


def grub_core_modules(data):
    """The modules grub-mkimage built into a GRUB EFI core image (empty if none)."""
    start = 0
    while (index := data.find(b'mimg', start)) >= 0 and index + 24 <= len(data):
        start = index + 1
        _, _, offset, size = struct.unpack_from('<IIQQ', data, index)
        if not (16 <= offset <= 32 and 24 <= size <= len(data) - index):
            continue
        position, end, names = index + offset, index + size, set()
        while position + 8 <= end:
            kind, length = struct.unpack_from('<II', data, position)
            if length < 8 or position + length > end:
                names = set()
                break
            if kind == 0:  # an ELF module object
                names.add(elf_section(data[position + 8:position + length], b'.modname')
                          .split(b'\0', 1)[0].decode())
            position += length
        if names:
            return names
    return set()


def elf_section(elf, wanted):
    if elf[:4] != b'\x7fELF':
        return b''
    table, = struct.unpack_from('<Q', elf, 0x28)
    size, count, strings = struct.unpack_from('<HHH', elf, 0x3a)

    def header(number):
        return struct.unpack_from('<IIQQQQ', elf, table + number * size)
    names = header(strings)[4]
    for number in range(count):
        name, _, _, _, offset, length = header(number)
        if elf[names + name:].split(b'\0', 1)[0] == wanted:
            return elf[offset:offset + length]
    return b''


def grub_statements(text):
    """GRUB script as (line, words): quotes removed, variables left in, and
    each { and } a statement of its own."""
    words, word, quote, quoted, line, start, index = [], '', None, False, 1, 1, 0

    def flush():
        statement = []
        for item in words:
            if item in ('{', '}'):
                if statement:
                    yield start, statement
                yield start, [item]
                statement = []
            else:
                statement.append(item)
        if statement:
            yield start, statement
    while index < len(text):
        char = text[index]
        if char == '\n':
            line += 1
        if quote:
            if char == quote:
                quote = None
            elif char == '\\' and quote == '"' and text[index + 1:index + 2] in ('"', '\\', '$'):
                index += 1
                word += text[index]
            else:
                word += char
        elif char in '\'"':
            quote, quoted = char, True
        elif char == '\\' and index + 1 < len(text):
            index += 1
            if text[index] == '\n':
                line += 1
            else:
                word += text[index]
        elif char == '#' and not word and not quoted:
            while index + 1 < len(text) and text[index + 1] != '\n':
                index += 1
        elif char in ' \t\n;':
            if word or quoted:
                words.append(word)
            word, quoted = '', False
            if char in '\n;' and words:
                yield from flush()
                words = []
        else:
            if not words and not word:
                start = line
            word += char
        index += 1
    if word or quoted:
        words.append(word)
    yield from flush()


def grub_expand(word, variables):
    """(text, unknown variable names) for $name and ${name} in a word."""
    unknown = []

    def value(match):
        name = match[1] or match[2]
        if name in variables:
            if variables[name] is GRUB_UNKNOWN:
                unknown.append(name)
                return ''
            return variables[name]
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) or name in GRUB_RUNTIME:
            unknown.append(name)
        return ''
    text = re.sub(r'\$\{([^}]*)\}|\$([A-Za-z_][A-Za-z0-9_]*|[0-9?#*@])', value, word)
    return text, unknown


def grub_value(word, variables):
    text, unknown = grub_expand(word, variables)
    return GRUB_UNKNOWN if unknown else text


def grub_test(words):
    if words[:1] == ['[']:
        return words[1:-1] if words[-1:] == [']'] else None
    return words[1:] if words[:1] == ['test'] else None


def grub_condition(words, variables):
    """True, False or None (not known before boot) for an if or while condition."""
    test = grub_test(words)
    if test is None:
        return None

    def split(tokens, operator):
        parts, part = [], []
        for token in tokens:
            if token == operator:
                parts.append(part)
                part = []
            else:
                part.append(token)
        return parts + [part]

    def either(tokens):
        values = [both(part) for part in split(tokens, '-o')]
        return True if True in values else False if all(value is False for value in values) else None

    def both(tokens):
        values = [single(part) for part in split(tokens, '-a')]
        return False if False in values else True if all(value is True for value in values) else None

    def single(tokens):
        if tokens[:1] == ['!']:
            value = single(tokens[1:])
            return None if value is None else not value
        values = [grub_value(token, variables) for token in tokens]
        if len(tokens) == 1 and values[0] is not GRUB_UNKNOWN:
            return values[0] != ''
        if len(tokens) == 2 and tokens[0] in ('-n', '-z') and values[1] is not GRUB_UNKNOWN:
            return (values[1] != '') == (tokens[0] == '-n')
        if len(tokens) == 3 and tokens[1] in ('=', '==', '!=') and GRUB_UNKNOWN not in (values[0], values[2]):
            return (values[0] == values[2]) == (tokens[1] != '!=')
        return None
    return either(test)


def grub_merge(paths):
    """The variables after one of several paths ran: a value they disagree on is unknown."""
    merged = {}
    for name in set().union(*paths):
        values = [path.get(name, '') for path in paths]
        merged[name] = values[0] if all(value == values[0] for value in values) else GRUB_UNKNOWN
    return merged


class GrubFiles:
    """The filesystems GRUB can reach: device -> (UUIDs, exists(path), read(path)).
    A filesystem this check cannot read has exists None."""

    def __init__(self, filesystems, core_modules=()):
        self.filesystems = {device: ({uuid.lower() for uuid in uuids}, exists, read)
                            for device, (uuids, exists, read) in filesystems.items()}
        self.core = set(core_modules)

    def device(self, uuid):
        return next((device for device, (uuids, _, _) in self.filesystems.items()
                     if uuid.lower() in uuids), None)

    def place(self, word, variables):
        """(device, path) of a GRUB file name, or why it cannot be resolved."""
        text, unknown = grub_expand(word, variables)
        if unknown:
            return f'${unknown[0]} is only known when GRUB runs'
        match = re.match(r'\(([^)]*)\)(.*)$', text)
        if match:
            device, path = match[1], match[2]
        else:
            device, path = variables.get('root', ''), text
            if device is GRUB_UNKNOWN:
                return '$root is only known when GRUB runs'
        if device not in self.filesystems:
            return f'({device}) is not a filesystem of this image'
        if self.filesystems[device][1] is None:
            return f'this check cannot read the {device} filesystem'
        if not path.startswith('/'):
            return f'{text} is not an absolute path'
        return device, re.sub('/+', '/', path)

    def exists(self, place):
        return self.filesystems[place[0]][1](place[1])

    def read(self, place):
        return self.filesystems[place[0]][2](place[1])


def grub_file_name(place):
    device, path = place
    return {'boot': f'/boot{path}', 'esp': path.lstrip('/')}.get(device, f'({device}){path}')


def grub_variables(root, prefix):
    variables = dict.fromkeys(GRUB_FEATURES, 'y')
    variables.update(grub_platform='efi', grub_cpu='arm64', root=root,
                     prefix=f'({root}){prefix}', config_directory=f'({root}){prefix}')
    return variables


def grub_references(text, name, files, variables, bls_entries=None, depth=0):
    """Problems with what one configuration names: modules, fonts, files, UUIDs."""
    problems = []

    def execute(statements, variables, guards):
        frames = []  # if: [reachable, decided, probes, before, paths]; loops: [True, ...]
        pending = []
        index = 0

        def report(line, problem):
            problems.append(f'{name}:{line}: {problem}')

        def probed():
            return guards | {path for frame in frames for path in frame[2]}

        def check(line, what, word):
            if grub_expand(word, variables) == ('', []):
                return None  # an unquoted word that expands to nothing is no argument
            place = files.place(word, variables)
            tested = probed()
            if isinstance(place, str):
                if word not in tested:
                    report(line, f'{what}: cannot resolve {word}: {place}')
                return None
            if any(files.place(path, variables) == place for path in tested):
                return place if files.exists(place) else None
            if not files.exists(place):
                report(line, f'{what}: {place[1]} is not on the {place[0]} filesystem')
                return None
            return place

        def follow(line, place, scope):
            if depth + 1 >= GRUB_DEPTH:
                report(line, f'{place[1]}: sources nest deeper than {GRUB_DEPTH}')
                return
            problems.extend(grub_references(files.read(place) or '', grub_file_name(place), files, scope,
                                            bls_entries, depth + 1))

        def command(line, words):
            head, args = words[0], words[1:]
            operands = [arg for arg in args if not arg.startswith('-')]
            if head == 'set' and args and '=' in args[0]:
                key, value = args[0].split('=', 1)
                variables[key] = grub_value(value, variables)
                if key == 'theme':
                    check(line, 'theme', value)
            elif re.match(r'[A-Za-z_][A-Za-z0-9_]*=', head) and not args:
                key, value = head.split('=', 1)
                variables[key] = grub_value(value, variables)
            elif head == 'unset':
                for key in args:
                    variables.pop(key, None)
            elif head.startswith('search'):
                search(line, head, args)
            elif head in ('regexp', 'probe'):
                for position, arg in enumerate(args):
                    target = arg[6:] if arg.startswith('--set=') else (
                        args[position + 1] if arg in ('--set', '-s') and position + 1 < len(args) else None)
                    if target:
                        variables[target.split(':')[-1]] = GRUB_UNKNOWN
            elif head == 'insmod':
                for module in operands:
                    if module not in files.core:
                        check(line, f'insmod {module}', f'$prefix/{GRUB_TARGET}/{module}.mod')
            elif head == 'loadfont':
                for font in operands:
                    check(line, f'loadfont {font}', font if font[:1] in '($/' else f'$prefix/fonts/{font}.pf2')
            elif head in ('load_env', 'save_env'):
                block = args[args.index('-f') + 1] if '-f' in args[:-1] else '$prefix/grubenv'
                place = check(line, head, block)
                if place and head == 'load_env':
                    wanted = [arg for arg in args if arg != block and not arg.startswith('-')]
                    for entry in (files.read(place) or '').splitlines():
                        key, equals, value = entry.partition('=')
                        if equals and not entry.startswith('#') and (not wanted or key in wanted):
                            variables[key] = value
            elif head in ('source', 'configfile') and operands:
                place = check(line, head, operands[0])
                if place and head == 'source':
                    follow(line, place, variables)
                elif place:
                    follow(line, place, dict(variables, config_directory=f'({place[0]}){place[1].rsplit("/", 1)[0]}'))
            elif head in ('linux', 'devicetree', 'chainloader') and operands:
                check(line, head, operands[0])
            elif head == 'initrd':
                for path in operands:
                    check(line, head, path)
            elif head == 'background_image':
                paths = [arg for position, arg in enumerate(args) if not arg.startswith('-')
                         and args[position - 1:position] not in (['-m'], ['--mode'])]
                if paths:
                    check(line, head, paths[-1])
            elif head == 'blscfg' and bls_entries is not None:
                for entry, entry_text in bls_entries():
                    for key, value in (row.split(None, 1) for row in entry_text.splitlines()
                                       if len(row.split(None, 1)) == 2):
                        if key in ('linux', 'initrd', 'devicetree'):
                            for path in value.split():
                                check(line, f'{entry}: {key}', path)

        def search(line, head, args):
            mode, target, key, position = {'search.fs_uuid': 'uuid', 'search.fs_label': 'label'}.get(
                head, 'file'), None, None, 0
            while position < len(args):
                arg = args[position]
                if arg in ('--fs-uuid', '-u'):
                    mode = 'uuid'
                elif arg in ('--label', '-l'):
                    mode = 'label'
                elif arg in ('--file', '-f'):
                    mode = 'file'
                elif arg.startswith('--set='):
                    target = arg[6:]
                elif arg in ('--set', '-s', '--hint', '-h'):
                    if arg in ('--set', '-s'):
                        target = args[position + 1] if position + 1 < len(args) else None
                    position += 1
                elif not arg.startswith('-'):
                    if key is None or head == 'search':
                        key = arg
                    elif target is None:
                        target = arg  # search.fs_uuid UUID VARIABLE
                position += 1
            target = target or 'root'
            uuid = grub_value(key or '', variables)
            if mode == 'uuid' and uuid:
                device = files.device(uuid)
                if device is None:
                    report(line, f'no filesystem in the image has the UUID {uuid}')
                variables[target] = device if device else GRUB_UNKNOWN
            else:
                variables[target] = GRUB_UNKNOWN  # by label or file: GRUB decides at boot

        def branch_end(frame):
            if frame[0]:
                frame[4].append(dict(variables))
            variables.clear()
            variables.update(frame[3])

        while index < len(statements):
            line, words = statements[index]
            index += 1
            while words and words[0] in ('then', 'do', 'else'):
                if words[0] == 'else' and frames and frames[-1][3] is not None:
                    frame = frames[-1]
                    branch_end(frame)
                    frame[0], frame[2] = not frame[1] and all(outer[0] for outer in frames[:-1]), set()
                    frame[1] = frame[1] or frame[0]
                words = words[1:]
            if not words:
                continue
            head = words[0]
            if head == '{' or (index < len(statements) and statements[index][1] == ['{']):
                if head != '{':
                    index += 1
                body, level = [], 1
                while index < len(statements):
                    item = statements[index]
                    index += 1
                    level += {'{': 1, '}': -1}.get(item[1][0], 0) if len(item[1]) == 1 else 0
                    if level == 0:
                        break
                    body.append(item)
                if level:
                    report(line, '{ is never closed')
                if all(frame[0] for frame in frames):
                    pending.append((body, probed()))
            elif head == '}':
                report(line, '} closes nothing')
            elif head in ('if', 'elif'):
                if head == 'if':
                    frames.append([True, False, set(), dict(variables), []])
                elif not frames or frames[-1][3] is None:
                    report(line, 'elif outside an if')
                    continue
                else:
                    branch_end(frames[-1])
                frame, condition = frames[-1], words[1:]
                frame[0] = False
                if not frame[1] and all(outer[0] for outer in frames[:-1]):
                    if condition and grub_test(condition) is None:
                        command(line, condition)
                    decided = grub_condition(condition, variables)
                    frame[0], frame[1] = decided is not False, decided is True
                test = grub_test(condition) or []
                frame[2] = {path for flag, path in zip(test, test[1:]) if flag in GRUB_PROBES}
            elif head == 'fi':
                if not frames or frames[-1][3] is None:
                    report(line, 'fi closes nothing')
                    continue
                frame = frames.pop()
                branch_end(frame)
                paths = frame[4] if frame[1] else frame[4] + [frame[3]]
                variables.clear()
                variables.update(grub_merge(paths) if paths else frame[3])
            elif head in ('for', 'while', 'until'):
                if head != 'for' and all(frame[0] for frame in frames):
                    command(line, words[1:])
                if head == 'for' and len(words) > 1:
                    variables[words[1]] = GRUB_UNKNOWN
                frames.append([all(frame[0] for frame in frames), False, set(), None, dict(variables)])
            elif head == 'done':
                if not frames or frames[-1][3] is not None:
                    report(line, 'done closes nothing')
                    continue
                before = frames.pop()[4]
                merged = grub_merge([before, dict(variables)])
                variables.clear()
                variables.update(merged)
            elif all(frame[0] for frame in frames):
                command(line, words)
        if frames:
            report(statements[-1][0] if statements else 0, 'an if or loop is never closed')
        # Menu entries and functions run after the configuration, each in a copy.
        for body, body_guards in pending:
            execute(body, dict(variables), body_guards)

    execute(list(grub_statements(text)), variables, set())
    return problems


def grub_configuration_problems(files, stubs, grub_dir, main, bls_entries=None):
    """The ESP stubs [(name, text, their directory)] and the configurations
    they hand over to, then /boot's grub.cfg as GRUB reads it from /boot."""
    problems = []
    for name, text, directory in stubs:
        problems += grub_references(text, name, files, grub_variables('esp', directory), bls_entries)
    problems += grub_references(main, grub_file_name(('boot', f'{grub_dir}/grub.cfg')), files,
                                grub_variables('boot', grub_dir), bls_entries)
    return list(dict.fromkeys(problems))


def tree_files(base):
    """exists(path) and read(path) for a filesystem copied to a directory."""
    root = Root(base)
    return (lambda name: root.path(name).is_file(),
            lambda name: root.path(name).read_text(errors='replace') if root.path(name).is_file() else None)


def unhinted_searches(text):
    return [line.strip() for line in text.splitlines()
            if re.match(r'\s*search\b', line) and ('--hint' not in line or '--no-floppy' not in line)]


def check_boot(args):
    esp, uuid = Path(args.esp), args.boot_uuid.lower()
    boot = Path(args.boot_dir)
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
    stub = esp / 'EFI/BOOT/grub.cfg'
    if not stub.is_file():
        return 'the EFI GRUB stub configuration is missing'
    text = stub.read_text()
    if PREAMBLE not in text or uuid not in text.lower():
        return f'EFI/BOOT/grub.cfg does not find /boot ({uuid}) by UUID on the startup disk'
    searches = unhinted_searches(text)
    if searches:
        return f'EFI/BOOT/grub.cfg has a lookup without a hint: {searches[0]}'
    main = boot / 'grub/grub.cfg'
    if not main.is_file():
        return '/boot/grub/grub.cfg is missing'
    main = main.read_text(errors='replace')
    searches = unhinted_searches(main)
    if searches:
        return f'/boot/grub/grub.cfg has a lookup without a hint: {searches[0]}'
    filesystems = {'boot': ({uuid}, *tree_files(boot)),
                   'esp': ({args.efi_uuid} if args.efi_uuid else set(), *tree_files(esp))}
    if args.root_uuid:
        # GRUB would read the root filesystem through its subvolume layout;
        # this check does not, so anything it names there fails closed.
        filesystems['root'] = ({args.root_uuid}, None, None)
    problems = grub_configuration_problems(GrubFiles(filesystems, grub_core_modules(data)),
                                           [('EFI/BOOT/grub.cfg', text, '/EFI/BOOT')], '/grub', main)
    return '; '.join(problems) or None


def check_logos(root):
    # Catch an absent or corrupt payload before publishing an image. Resolve
    # Nix store/profile symlinks inside the finished root, as for other basics.
    for size in (16, 22, 24, 32, 48, 64, 96, 128, 256, 512):
        for directory, name in (('apps', 'aurora-logo-icon'), ('places', 'start-here')):
            path = root.path(f'{root.usr}/share/icons/hicolor/{size}x{size}/{directory}/{name}.png')
            if not path.is_file() or path.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
                return f'missing or invalid Aurora icon: {name} ({size}px)'
    path = root.path(f'{root.usr}/share/pixmaps/system-logo-white.png')
    if not path.is_file() or path.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
        return 'missing or invalid Aurora About logo'
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--profile', required=True, choices=['kde', 'gnome', 'minimal'])
    parser.add_argument('--root', help='the finished image root')
    parser.add_argument('--system', help='NixOS: the system closure installed in the root')
    parser.add_argument('--esp', help='the EFI partition contents')
    parser.add_argument('--boot-dir', help='the /boot filesystem contents')
    parser.add_argument('--boot-uuid', help='the /boot filesystem UUID')
    parser.add_argument('--efi-uuid', help='the EFI partition\'s filesystem UUID (XXXX-XXXX)')
    parser.add_argument('--root-uuid', help='the root filesystem UUID')
    args = parser.parse_args()
    if not args.root and not args.esp:
        parser.error('nothing to check: give --root, --esp or both')
    if args.esp and not (args.boot_uuid and args.boot_dir):
        parser.error('--esp needs --boot-uuid and --boot-dir')
    checks = []
    if args.root:
        root = Root(args.root, args.system)
        checks.append(('locale', check_locale(root)))
        checks.append(('gl-selection', check_gl_selection(root)))
        if args.profile != 'minimal':
            checks.append(('terminal', check_terminal(root, args.profile)))
            checks.append(('wallpaper', check_wallpaper(root, args.profile)))
            checks.append(('logos', check_logos(root)))
        checks.append(('network', check_network(root, args.profile)))
        checks.append(('usb4', check_usb4(root, args.profile)))
        checks.append(('lid', check_lid(root)))
        checks.append(('touchid', check_touchid(root, args.profile)))
        checks.append(('greeter', check_greeter(root, args.profile)))
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
