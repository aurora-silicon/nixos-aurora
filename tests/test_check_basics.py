from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/check-basics.py'
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


def logos(usr):
    for size in (16, 22, 24, 32, 48, 64, 96, 128, 256, 512):
        for directory, name in (('apps', 'aurora-logo-icon'), ('places', 'start-here')):
            write(usr / f'share/icons/hicolor/{size}x{size}/{directory}/{name}.png', b'\x89PNG\r\n\x1a\n')
    write(usr / 'share/pixmaps/system-logo-white.png', b'\x89PNG\r\n\x1a\n')


# Touch ID as Aurora ships it: fingerprint for sudo, polkit and the lock
# screen, the password everywhere else; a short power-button press suspends.
FPRINTD = '-auth sufficient pam_fprintd.so\n'
SYSTEM_AUTH = 'auth [success=1 default=bad] pam_unix.so try_first_pass nullok\nauth optional pam_permit.so\n'
STACK = 'auth include system-auth\naccount include system-auth\n'
LOCK = 'auth required pam_shells.so\n-auth required pam_fprintd.so\nauth optional pam_permit.so\n'
LOGIND = '[Login]\nHandlePowerKey=suspend\nHandlePowerKeyLongPress=poweroff\n'
POWERDEVIL = ''.join(f'[{group}][SuspendAndShutdown]\nPowerButtonAction=1\n'
                     for group in ('AC', 'Battery', 'LowBattery'))


def touchid_files(etc, profile):
    pam = etc / 'pam.d'
    write(pam / 'system-auth', SYSTEM_AUTH)
    write(pam / 'system-login', 'auth required pam_shells.so\nauth include system-auth\n')
    write(pam / 'sudo', FPRINTD + STACK)
    write(pam / 'polkit-1', FPRINTD + STACK)
    write(pam / 'login', 'auth include system-login\n')
    write(pam / 'su', 'auth sufficient pam_rootok.so\nauth required pam_unix.so\n')
    write(pam / 'sshd', 'auth include system-login\n')
    services = {'gnome': {'gdm-fingerprint': LOCK, 'gdm-password': 'auth include system-login\n'},
                'kde': {'kde-fingerprint': LOCK, 'kde': 'auth include system-login\n',
                        'plasmalogin': 'auth include system-login\n'}}
    for name, text in services.get(profile, {}).items():
        write(pam / name, text)
    write(etc / 'systemd/logind.conf.d/50-aurora-sep.conf', LOGIND)
    if profile == 'kde':
        write(etc / 'xdg/powerdevilrc', POWERDEVIL)


class CheckBasicsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)

    def fresh(self):
        self.temporary.cleanup()
        self.setUp()

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
        touchid_files(e, profile)
        if profile != 'minimal':
            logos(u)
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
            write(u / 'share/applications/kcm_networkmanagement.desktop')
            for name in ('Next', 'Air', 'Horos', 'Altai', 'Kokkini', 'Canopee', 'Cluster', 'Flow', 'Mountain'):
                write(u / f'share/wallpapers/{name}/contents/images/1920x1080.png')
            # systemctl enable plasmalogin.service links its Alias=.
            write(root / 'usr/lib/systemd/system/plasmalogin.service', '[Service]\nExecStart=/usr/bin/plasmalogin\n')
            link(e / 'systemd/system/display-manager.service', '/usr/lib/systemd/system/plasmalogin.service')
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

    def test_global_gl_selector_fails(self):
        self.assert_fails('gnome', lambda root: write(root / 'etc/environment',
                          'MESA_LOADER_DRIVER_OVERRIDE="zink"\n'), 'global MESA_LOADER_DRIVER_OVERRIDE')

    def test_global_gallium_environment_d_fails(self):
        self.assert_fails('minimal', lambda root: write(root / 'usr/lib/environment.d/90-gl.conf',
                          "export GALLIUM_DRIVER='zink'\n"), 'global GALLIUM_DRIVER')

    def test_no_gl_selector_or_empty_value_passes(self):
        root = self.desktop_root('gnome')
        write(root / 'etc/environment', '# MESA_LOADER_DRIVER_OVERRIDE=zink\nLANG=en_US.UTF-8\n')
        write(root / 'etc/environment.d/90-gl.conf', 'GALLIUM_DRIVER=""\n')
        result = self.check('--profile', 'gnome', '--root', str(root))
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_nixos_session_gl_selector_fails(self):
        self.assert_fails('gnome', lambda root: write(root / 'etc/set-environment',
                          'export MESA_LOADER_DRIVER_OVERRIDE=zink\n'), 'global MESA_LOADER_DRIVER_OVERRIDE')

    def test_c_locale_fails(self):
        self.assert_fails('gnome', lambda root: write(root / 'etc/locale.conf', 'LANG=C\n'), 'locale: FAIL')

    def test_ungenerated_locale_fails(self):
        self.assert_fails('minimal', lambda root: write(root / 'usr/lib/locale/locale-archive', b'\0de_DE.utf8\0'),
                          'is not generated')

    def test_missing_launcher_icon_fails(self):
        self.assert_fails('kde', lambda root: (
            root / 'usr/share/icons/hicolor/32x32/places/start-here.png').unlink(), 'logos: FAIL')

    def test_corrupt_about_logo_fails(self):
        self.assert_fails('kde', lambda root: write(
            root / 'usr/share/pixmaps/system-logo-white.png', b'broken'), 'logos: FAIL')

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
            # What plasma-workspace alone ships: Next, Air and Horos.
            for name in ('Altai', 'Kokkini', 'Canopee', 'Cluster', 'Flow', 'Mountain'):
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

    def test_kde_with_sddm_fails(self):
        def mutate(root):
            write(root / 'usr/lib/systemd/system/sddm.service', '[Service]\nExecStart=/usr/bin/sddm\n')
            (root / 'etc/systemd/system/display-manager.service').unlink()
            link(root / 'etc/systemd/system/display-manager.service', '/usr/lib/systemd/system/sddm.service')
        self.assert_fails('kde', mutate, 'the display manager is sddm.service, not Plasma Login')

    def test_kde_without_a_display_manager_fails(self):
        self.assert_fails('kde', lambda root: (root / 'etc/systemd/system/display-manager.service').unlink(),
                          'no display manager is enabled')

    def test_nixos_plasma_login_alias_is_followed_into_the_store(self):
        # NixOS: display-manager.service -> plasmalogin.service (aliases=),
        # which links the package's unit; /etc/systemd/system is in the store.
        root = self.base / 'root'
        system, units = '/nix/store/aaaa-nixos-system', '/nix/store/cccc-system-units'
        unit = '/nix/store/dddd-plasma-login-manager/lib/systemd/system/plasmalogin.service'
        link(root / system.lstrip('/') / 'etc', '/nix/store/bbbb-etc/etc')
        link(root / 'nix/store/bbbb-etc/etc/systemd/system', units)
        write(root / unit.lstrip('/'), '[Service]\nExecStart=plasmalogin\n')
        link(root / units.lstrip('/') / 'plasmalogin.service', unit)
        link(root / units.lstrip('/') / 'display-manager.service', 'plasmalogin.service')
        result = self.check('--profile', 'kde', '--root', str(root), '--system', system)
        self.assertIn('greeter: ok', result.stdout)
        # A generic display-manager.service unit, as NixOS's GDM and SDDM use.
        generic = '/nix/store/eeee-unit-display-manager.service/display-manager.service'
        (root / units.lstrip('/') / 'display-manager.service').unlink()
        write(root / generic.lstrip('/'), '[Service]\nExecStart=sddm\n')
        link(root / units.lstrip('/') / 'display-manager.service', generic)
        result = self.check('--profile', 'kde', '--root', str(root), '--system', system)
        self.assertIn('greeter: FAIL: the display manager is display-manager.service, not Plasma Login', result.stdout)

    def test_fingerprint_at_the_console_login_fails(self):
        self.assert_fails('minimal', lambda root: write(root / 'etc/pam.d/system-login',
                          FPRINTD + 'auth include system-auth\n'), 'login offers a fingerprint')

    def test_sudo_and_polkit_without_fingerprint_fail(self):
        def mutate(root):
            write(root / 'etc/pam.d/sudo', STACK)
            write(root / 'etc/pam.d/polkit-1', STACK)
        self.assert_fails('gnome', mutate, 'sudo does not offer a fingerprint; polkit-1 does not offer a fingerprint')

    def test_fingerprint_that_replaces_the_password_fails(self):
        self.assert_fails('minimal', lambda root: write(root / 'etc/pam.d/sudo',
                          'auth required pam_fprintd.so\n' + STACK), 'sudo has no password after the fingerprint')

    def test_fingerprint_at_the_login_screen_fails(self):
        self.assert_fails('kde', lambda root: write(root / 'etc/pam.d/plasmalogin', FPRINTD + STACK),
                          'plasmalogin offers a fingerprint')

    def test_lock_screen_without_fingerprint_fails(self):
        self.assert_fails('kde', lambda root: write(root / 'etc/pam.d/kde-fingerprint', 'auth required pam_deny.so\n'),
                          'kde-fingerprint does not offer a fingerprint')

    def test_vendor_pam_directory_is_read(self):
        def mutate(root):
            (root / 'etc/pam.d/polkit-1').unlink()
            write(root / 'usr/lib/pam.d/polkit-1', STACK)
        self.assert_fails('minimal', mutate, 'polkit-1 does not offer a fingerprint')

    def test_power_key_that_powers_off_fails(self):
        self.assert_fails('minimal', lambda root: (root / 'etc/systemd/logind.conf.d/50-aurora-sep.conf').unlink(),
                          'logind HandlePowerKey=(default), not suspend')
        self.fresh()
        self.assert_fails('gnome', lambda root: write(root / 'etc/systemd/logind.conf.d/90-local.conf',
                          '[Login]\nHandlePowerKey=poweroff\n'), 'logind HandlePowerKey=poweroff, not suspend')

    def test_plasma_power_button_must_suspend(self):
        self.assert_fails('kde', lambda root: (root / 'etc/xdg/powerdevilrc').unlink(),
                          'Plasma AC power button action is the logout screen, not suspend')

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
        # Follow the package link through the system profile inside the root.
        logo_path = '/nix/store/ffff-aurora-logos/share/icons/hicolor'
        logos(root / 'nix/store/ffff-aurora-logos')
        link(root / sw.lstrip('/') / 'share/icons/hicolor', logo_path)
        link(root / sw.lstrip('/') / 'share/pixmaps', '/nix/store/ffff-aurora-logos/share/pixmaps')
        touchid_files(root / etc.lstrip('/'), 'gnome')
        result = self.check('--profile', 'gnome', '--root', str(root), '--system', system, *self.boot())
        self.assertEqual(result.returncode, 0, result.stdout)
        write(root / etc.lstrip('/') / 'locale.conf', 'LANG=C\n')
        self.assertNotEqual(self.check('--profile', 'gnome', '--root', str(root), '--system', system).returncode, 0)


if __name__ == '__main__':
    unittest.main()
