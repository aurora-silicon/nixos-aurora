"""dbus-service-names.py finds the names dbus-broker would read twice."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dbus_names', ROOT / 'scripts/dbus-service-names.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def service(path, name):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'[D-BUS Service]\nName={name}\nExec=/bin/true\n')


class DbusServiceNameTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        store = self.root / 'store'
        old = module.STORE
        module.STORE = f'{store}/'
        self.addCleanup(setattr, module, 'STORE', old)
        # A package installed system-wide and named in services.dbus.packages.
        self.upower = store / 'aaa-upower'
        service(self.upower / 'share/dbus-1/system-services/org.freedesktop.UPower.service', 'org.freedesktop.UPower')
        service(self.upower / 'share/dbus-1/services/org.example.Tray.service', 'org.example.Tray')
        # Only in services.dbus.packages.
        self.gcr = store / 'bbb-gcr'
        service(self.gcr / 'share/dbus-1/services/org.gnome.keyring.SystemPrompter.service', 'org.gnome.keyring.SystemPrompter')
        self.sw = store / 'ccc-system-path'
        for bus in ('system-services', 'services'):
            (self.sw / 'share/dbus-1' / bus).mkdir(parents=True)
            for f in (self.upower / 'share/dbus-1' / bus).iterdir():
                os.symlink(f, self.sw / 'share/dbus-1' / bus / f.name)
        self.top = self.root / 'system'
        (self.top / 'etc/dbus-1').mkdir(parents=True)
        (self.top / 'etc/pam').mkdir()
        (self.top / 'etc/pam/environment').write_text(
            'XDG_DATA_DIRS   DEFAULT="@{HOME}/.nix-profile/share:/etc/profiles/per-user/@{PAM_USER}/share:'
            '/run/current-system/sw/share"\n')
        os.symlink(self.sw, self.top / 'sw')

    def conf(self, bus, packages, standard=''):
        dirs = ''.join(f'<servicedir>{p}/share/dbus-1/{bus}</servicedir>' for p in packages)
        name = 'system' if bus == 'system-services' else 'session'
        (self.top / f'etc/dbus-1/{name}.conf').write_text(f'<busconfig>{standard}{dirs}</busconfig>')

    def scan(self, bus):
        names, duplicates = module.System(self.top).scan(bus)
        return sorted(names), [name for name, _, _ in duplicates]

    def test_nixos_lists_system_path_and_the_package(self):
        self.conf('system-services', [self.sw, self.upower, self.gcr])
        self.conf('services', [self.sw, self.upower, self.gcr], '<standard_session_servicedirs/>')
        self.assertEqual(self.scan('system'), (['org.freedesktop.UPower'], ['org.freedesktop.UPower']))
        self.assertEqual(self.scan('session'), (['org.example.Tray', 'org.gnome.keyring.SystemPrompter'],
                                                ['org.example.Tray', 'org.example.Tray']))

    def test_each_file_once_keeps_every_name(self):
        self.conf('system-services', [self.sw, self.gcr])
        self.conf('services', [self.gcr], '<standard_session_servicedirs/>')
        self.assertEqual(self.scan('system'), (['org.freedesktop.UPower'], []))
        self.assertEqual(self.scan('session'), (['org.example.Tray', 'org.gnome.keyring.SystemPrompter'], []))

    def test_two_packages_declaring_one_name_are_found(self):
        service(self.gcr / 'share/dbus-1/services/org.example.Other.service', 'org.example.Tray')
        self.conf('system-services', [self.sw])
        self.conf('services', [self.gcr], '<standard_session_servicedirs/>')
        self.assertEqual(self.scan('session')[1], ['org.example.Tray'])


if __name__ == '__main__':
    unittest.main()
