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
    searches = unhinted_searches(main.read_text(errors='replace'))
    if searches:
        return f'/boot/grub/grub.cfg has a lookup without a hint: {searches[0]}'
    return None


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
