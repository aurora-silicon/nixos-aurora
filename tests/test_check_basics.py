from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/check-basics'
BOOT = '2025cecd-807c-5835-9ad4-e547cfdeb279'
PREAMBLE = '# Aurora: look for this installation only on the disk GRUB started from.\n'


def write(path, text='', mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text)
    if mode:
        path.chmod(mode)


def link(path, target):
    path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, path)


class CheckBasicsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def check(self, *arguments):
        return subprocess.run([sys.executable, str(SCRIPT), *arguments], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True)

    def desktop_root(self, profile, usr='usr', etc='etc'):
        root = self.base / 'root'
        u, e = root / usr, root / etc
        write(e / 'locale.conf', 'LANG=en_US.UTF-8\n')
        write(root / 'usr/lib/locale/locale-archive', b'\0en_US.utf8\0')
        link(e / 'systemd/system/multi-user.target.wants/NetworkManager.service',
             '/usr/lib/systemd/system/NetworkManager.service')
        if profile == 'gnome':
            write(u / 'bin/kgx', mode=0o755)
            write(u / 'share/applications/org.gnome.Console.desktop')
            write(u / 'bin/gnome-control-center', mode=0o755)
            write(u / 'share/backgrounds/gnome/adwaita-l.jxl')
            write(u / 'share/glib-2.0/schemas/org.gnome.desktop.background.gschema.xml',
                  "<key name=\"picture-uri\" type=\"s\">\n<default>'file:///usr/share/backgrounds/gnome/adwaita-l.jxl'</default>")
        if profile == 'kde':
            write(u / 'bin/konsole', mode=0o755)
            write(u / 'share/applications/org.kde.konsole.desktop')
            (u / 'share/plasma/plasmoids/org.kde.plasma.networkmanagement').mkdir(parents=True)
            for name in ('Next', 'Altai', 'Kokkini'):
                write(u / f'share/wallpapers/{name}/contents/images/1920x1080.png')
        return root

    def boot(self):
        esp, boot = self.base / 'esp', self.base / 'boot'
        write(esp / 'EFI/BOOT/BOOTAA64.EFI', b'MZ\0/EFI/BOOT\0')
        write(esp / 'EFI/BOOT/grub.cfg', PREAMBLE + f'probe --set=aurora_uuid --fs-uuid "($aurora_disk,gpt$n)"\n'
              f'  search --no-floppy --fs-uuid --set=root --hint="$aurora_boot" {BOOT}\n')
        write(boot / 'grub/grub.cfg', f'search --no-floppy --fs-uuid --set=root --hint="${{aurora_disk}}," {BOOT}\n')
        return ['--esp', str(esp), '--boot-dir', str(boot), '--boot-uuid', BOOT]

    def test_complete_images_pass(self):
        for profile in ('gnome', 'kde', 'minimal'):
            with self.subTest(profile=profile):
                root = self.desktop_root(profile)
                result = self.check('--profile', profile, '--root', str(root), *self.boot())
                self.assertEqual(result.returncode, 0, result.stdout)
                self.temporary.cleanup()
                self.temporary = tempfile.TemporaryDirectory()
                self.base = Path(self.temporary.name)

    def assert_fails(self, profile, mutate, expected):
        root = self.desktop_root(profile)
        boot = self.boot()
        mutate(root)
        result = self.check('--profile', profile, '--root', str(root), *boot)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(expected, result.stdout)

    def test_c_locale_fails(self):
        self.assert_fails('gnome', lambda root: write(root / 'etc/locale.conf', 'LANG=C\n'), 'locale: FAIL')

    def test_ungenerated_locale_fails(self):
        self.assert_fails('minimal', lambda root: write(root / 'usr/lib/locale/locale-archive', b'\0de_DE.utf8\0'),
                          'is not generated')

    def test_missing_terminal_fails(self):
        self.assert_fails('kde', lambda root: (root / 'usr/bin/konsole').unlink(), 'terminal: FAIL')

    def test_missing_gnome_backgrounds_fails(self):
        self.assert_fails('gnome', lambda root: (root / 'usr/share/backgrounds/gnome/adwaita-l.jxl').unlink(),
                          'gnome-backgrounds')

    def test_default_gnome_picture_must_exist(self):
        def mutate(root):
            write(root / 'usr/share/glib-2.0/schemas/10_vendor.gschema.override',
                  "[org.gnome.desktop.background]\npicture-uri='file:///usr/share/backgrounds/vendor/missing.png'\n")
        self.assert_fails('gnome', mutate, 'does not exist')

    def test_missing_plasma_wallpapers_fails(self):
        def mutate(root):
            for name in ('Altai', 'Kokkini'):
                (root / f'usr/share/wallpapers/{name}/contents/images/1920x1080.png').unlink()
        self.assert_fails('kde', mutate, 'plasma-workspace-wallpapers')

    def test_disabled_networkmanager_fails(self):
        self.assert_fails('minimal', lambda root: (
            root / 'etc/systemd/system/multi-user.target.wants/NetworkManager.service').unlink(), 'network: FAIL')

    def test_lid_policy_and_masked_sleep_fail(self):
        self.assert_fails('minimal', lambda root: write(root / 'etc/systemd/logind.conf.d/10-lid.conf',
                                                         '[Login]\nHandleLidSwitch=ignore\n'), 'HandleLidSwitch=ignore')
        self.temporary.cleanup()
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.assert_fails('minimal', lambda root: link(root / 'etc/systemd/system/suspend.target', '/dev/null'),
                          'suspend.target is masked')

    def test_core_with_an_early_uuid_search_fails(self):
        self.assert_fails('minimal', lambda root: write(self.base / 'esp/EFI/BOOT/BOOTAA64.EFI',
                                                         f'MZ\0/EFI/BOOT\0search.fs_uuid {BOOT} root\0'.encode()),
                          'all-disk search')

    def test_partition_numbered_core_fails(self):
        self.assert_fails('minimal', lambda root: write(self.base / 'esp/EFI/BOOT/BOOTAA64.EFI',
                                                         b'MZ\0(,gpt2)/grub\0'), 'partition number')

    def test_unhinted_search_fails(self):
        self.assert_fails('minimal', lambda root: write(self.base / 'boot/grub/grub.cfg',
                                                         f'search --no-floppy --fs-uuid --set=root {BOOT}\n'),
                          'without a hint')

    def test_stub_must_name_the_boot_uuid(self):
        self.assert_fails('minimal', lambda root: write(self.base / 'esp/EFI/BOOT/grub.cfg', PREAMBLE),
                          'by UUID on the startup disk')

    def test_nixos_system_closure_is_read_through_store_links(self):
        root = self.base / 'root'
        system = '/nix/store/aaaa-nixos-system'
        sw = '/nix/store/bbbb-system-path'
        etc = '/nix/store/cccc-etc/etc'
        link(root / system.lstrip('/') / 'sw', sw)
        link(root / system.lstrip('/') / 'etc', etc)
        write(root / etc.lstrip('/') / 'locale.conf', 'LANG=en_US.UTF-8\n')
        write(root / etc.lstrip('/') / 'set-environment',
              'export LOCALE_ARCHIVE="/nix/store/dddd-glibc-locales/lib/locale/locale-archive"\n')
        write(root / 'nix/store/dddd-glibc-locales/lib/locale/locale-archive', b'\0en_US.utf8\0')
        link(root / etc.lstrip('/') / 'systemd/system/multi-user.target.wants/NetworkManager.service',
             '/nix/store/eeee-unit/NetworkManager.service')
        write(root / sw.lstrip('/') / 'bin/kgx', mode=0o755)
        write(root / sw.lstrip('/') / 'share/applications/org.gnome.Console.desktop')
        write(root / sw.lstrip('/') / 'bin/gnome-control-center', mode=0o755)
        write(root / sw.lstrip('/') / 'share/backgrounds/gnome/adwaita-l.jxl')
        result = self.check('--profile', 'gnome', '--root', str(root), '--system', system, *self.boot())
        self.assertEqual(result.returncode, 0, result.stdout)
        write(root / etc.lstrip('/') / 'locale.conf', 'LANG=C\n')
        self.assertNotEqual(self.check('--profile', 'gnome', '--root', str(root), '--system', system).returncode, 0)


if __name__ == '__main__':
    unittest.main()
