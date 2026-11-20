"""The M5 Pro and Max (T6050) load apple_sep with SEP writes off by default.

xART is shared with macOS, and its write paths (keybag provisioning, Touch
ID enrolment) have had no trial on a T6050. So on a device tree that names
apple,t6050, load-driver puts "xart_writes=0 provision_keybag=0" in
/run/modprobe.d/aurora-sep.conf, which stands in for the packaged defaults,
unless the owner's /etc/modprobe.d/aurora-sep.conf sets both options. Every
other Mac keeps the packaged defaults.

The kernel (7.3.0-41, 7.3.0-43) refuses a second value of an apple_sep
parameter and does not load the driver, and a parameter nobody sets keeps
the kernel's default, writes on. So on a T6050 load-driver checks what kmod
will pass, the kernel command line included: each of the two exactly once,
0 or 1, and does not load the driver (or finish the initrd's attach)
otherwise. With provisioning off and no keybag there is nothing to probe,
and load-driver ends without a failure.

modprobe is a stub that asks the real kmod what it would pass.
"""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SEP = ROOT / 'sep'
LOAD_DRIVER = SEP / 'load-driver'
# Where modules/sep.nix puts the files, under the test's root: NixOS has no
# /usr/lib/modprobe.d, so the defaults are copied to /run at boot.
DEFAULTS = 'run/modprobe.d/aurora-sep.conf'
BLACKLIST = ('etc/modprobe.d/nixos.conf', 'blacklist apple_sep\n')
KMOD = shutil.which('modprobe', path=os.environ.get('PATH', '') + ':/usr/sbin:/sbin')

READ_ONLY = ['xart_writes=0', 'provision_keybag=0']
WRITES_ON = ['xart_writes=1', 'provision_keybag=1']
OWNER_ON = 'options apple_sep xart_writes=1 provision_keybag=1\n'

T6050_BOARDS = ('j714s', 'k116s', 'j716c')
OTHER_MACS = (('j815', 't8142'), ('j614c', 't6041'), ('j616s', 't6040'), ('j700', 't8140'),
              ('j713', 't8132'), ('j414s', 't6020'), ('j293', 't8103'))

# /etc/modprobe.d/aurora-sep.conf files that must not load the driver on a
# T6050: each would leave a parameter at the kernel's writes-on default, give
# one twice, or give the driver a value it refuses.
WRONG_OWNER_FILES = {
    'empty': '',
    'comment only': '# opted in\n',
    'other options only': 'options apple_sep sensor_trace=1\n',
    'the xart_guard opt-out only': 'options apple_sep xart_guard=0\n',
    'a typo': 'options apple_sep xart_write=0 provision_keybag=0\n',
    'no provision_keybag': 'options apple_sep xart_writes=0\n',
    'a duplicate': 'options apple_sep xart_writes=0 xart_writes=0 provision_keybag=0\n',
    'a duplicate across lines': OWNER_ON + 'options apple_sep xart_writes=1\n',
    'a value other than 0 or 1': 'options apple_sep xart_writes=2 provision_keybag=0\n',
    'a bare name': 'options apple_sep xart_writes provision_keybag=0\n',
    'a bare name beside a value': 'options apple_sep xart_writes xart_writes=0 provision_keybag=0\n',
    'provisioning without writes': 'options apple_sep xart_writes=0 provision_keybag=1\n',
    # The kernel stops reading options at a bare '--', and reads '"' as a
    # quote that can swallow what follows.
    'a bare --': 'options apple_sep -- xart_writes=0 provision_keybag=0\n',
    'a quote swallowing both': 'options apple_sep x="y xart_writes=0 provision_keybag=0 "\n',
    # modprobe.d has no comments after an option: kmod passes them on.
    'a comment after the options': 'options apple_sep xart_writes=0 provision_keybag=0 # read-only\n',
}

# Other modprobe.d files (or the owner's path holding something else than a
# regular file) that would give the driver writes while the options look
# read-only: each stops the load on a T6050 with no owner file.
HIDDEN_WRITES = {
    'a bare -- in another file': {'etc/modprobe.d/00-local.conf': 'options apple_sep --\n'},
    'an open quote in another file': {'etc/modprobe.d/00-local.conf': 'options apple_sep xart_gaurd="0\n'},
    'an install command with insmod': {'etc/modprobe.d/00-local.conf':
        'install apple_sep /usr/bin/insmod /lib/modules/7.3.0/kernel/drivers/soc/apple/apple-sep.ko\n'},
    'an install command with modprobe': {'etc/modprobe.d/00-local.conf':
        'install apple_sep /usr/bin/modprobe --ignore-install apple_sep\n'},
    'an install command found on PATH': {'etc/modprobe.d/00-local.conf':
        'install apple_sep modprobe --ignore-install apple_sep\n'},
    'a directory at the owner path': {'etc/modprobe.d/aurora-sep.conf': ('dir', None)},
    'a link from the owner path to /dev/null': {'etc/modprobe.d/aurora-sep.conf': ('link', '/dev/null')},
    'a dangling link at the owner path': {'etc/modprobe.d/aurora-sep.conf': ('link', '/nonexistent.conf')},
}

# -c prints the configuration kmod reads from the test's root, then KCMDLINE
# as kmod prints apple_sep.* from the kernel command line (after the files).
# Anything else is a load, logged with the apple_sep options kmod would pass.
MODPROBE = r'''#!/bin/sh
CONFIG=
for d in etc/modprobe.d run/modprobe.d usr/lib/modprobe.d; do
    # SKIP_RUN: kmod does not read /run (as if SELinux kept it out).
    [ -n "${SKIP_RUN:-}" ] && [ "$d" = run/modprobe.d ] && continue
    [ -d "$TEST_ROOT/$d" ] && CONFIG="$CONFIG --config=$TEST_ROOT/$d"
done
config() {
    "$KMOD" $CONFIG -c
    [ -z "${KCMDLINE:-}" ] || echo "options apple_sep $KCMDLINE"
}
if [ "$*" = -c ]; then
    config
    exit
fi
echo "load $*" >>"$MODPROBE_LOG"
config | sed -n 's/^options apple_sep /options /p' >>"$MODPROBE_LOG"
'''

# A key store that never seals a key.
KEYCTL = '''#!/bin/sh
echo "$*" >>"$KEYCTL_LOG"
exit 1
'''


def compatible(board, soc):
    return f'apple,{board}\0apple,{soc}\0apple,arm-platform\0'


@unittest.skipUnless(KMOD, 'needs kmod')
class LoadDriverCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        tmp = Path(temporary.name)
        self.root = tmp / 'root'
        self.install(DEFAULTS, (SEP / 'aurora-sep-modprobe.conf').read_text())
        self.install(*BLACKLIST)
        (self.root / 'etc/modprobe.d').mkdir(parents=True, exist_ok=True)
        # No *.sep device unless a test adds one: load-driver then stops
        # after loading the driver.
        self.sysfs = tmp / 'devices'
        self.sysfs.mkdir()
        bin_dir = tmp / 'bin'
        bin_dir.mkdir()
        scratch = shlex.quote(f'{tmp}/aurora-sep-load.XXXXXX')
        for name, body in (('modprobe', MODPROBE), ('keyctl', KEYCTL),
                           ('mktemp', f'#!/bin/sh\nexec {shlex.quote(shutil.which("mktemp"))} -d {scratch}\n')):
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
        self.log = tmp / 'modprobe.log'
        self.log.touch()
        self.keyctl_log = tmp / 'keyctl.log'
        self.keyctl_log.touch()
        self.packaged = self.run_files()
        self.env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}',
                        AURORA_SEP_SESSION='1', AURORA_SEP_SYSFS=str(self.sysfs),
                        AURORA_SEP_ROOT=str(self.root), AURORA_SEP_READY_TIMEOUT='5',
                        TEST_ROOT=str(self.root), KMOD=KMOD, MODPROBE_LOG=str(self.log),
                        KEYCTL_LOG=str(self.keyctl_log))
        self.env.pop('KCMDLINE', None)

    def install(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if text == ('dir', None):
            path.mkdir()
        elif isinstance(text, tuple):
            path.symlink_to(text[1])
        else:
            path.write_text(text)

    def mac(self, board='j714s', soc='t6050'):
        self.install('proc/device-tree/compatible', compatible(board, soc))

    def sep_device(self, **diag):
        """A SEP device whose bring-up has ended, with these diag values."""
        attrs = self.sysfs / '2c3800000.sep/diag'
        attrs.mkdir(parents=True)
        for name, value in dict(dict(keystore='open', keybag='unknown'), **diag).items():
            (attrs / name).write_text(f'{value}\n')

    def run_files(self):
        run = self.root / 'run/modprobe.d'
        return {p.name: p.read_text() for p in run.iterdir()} if run.is_dir() else {}

    def run_load_driver(self):
        return subprocess.run(['sh', str(LOAD_DRIVER)], env=self.env, capture_output=True,
                              text=True, check=False, timeout=60)

    def loads(self):
        """[(argv, options)] for every load: the options in the order kmod
        passes them, each line of every file and the kernel command line."""
        loads = []
        for line in self.log.read_text().splitlines():
            words = shlex.split(line)
            if words[0] == 'load':
                loads.append((words[1:], []))
            else:
                loads[-1][1].extend(words[1:])
        return loads

    def probes(self):
        return [l for l in self.keyctl_log.read_text().splitlines()
                if l.startswith('padd trusted aurora-sep-check')]

    def assert_loaded_once_with(self, done, options):
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.loads()), 1, done.stderr)
        argv, given = self.loads()[0]
        self.assertEqual(argv, ['apple_sep'])
        # Each parameter once: a second value fails the load.
        self.assertCountEqual(given, options)

    def assert_not_loaded(self, done, *messages):
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(self.loads(), [])
        for message in messages:
            self.assertIn(message, done.stderr)


class T6050ReadOnlyTest(LoadDriverCase):
    def test_a_t6050_loads_the_driver_read_only(self):
        for board in T6050_BOARDS:
            with self.subTest(board=board):
                self.setUp()
                self.mac(board)
                done = self.run_load_driver()
                self.assert_loaded_once_with(done, READ_ONLY)
                self.assertEqual(self.run_files(), {
                    'aurora-sep.conf': 'options apple_sep xart_writes=0 provision_keybag=0\n'})
                self.assertIn('SEP writes are off by default on this Mac (T6050)', done.stderr)

    def test_other_macs_keep_the_packaged_defaults(self):
        for board, soc in OTHER_MACS:
            with self.subTest(soc=soc):
                self.setUp()
                self.mac(board, soc)
                done = self.run_load_driver()
                self.assert_loaded_once_with(done, WRITES_ON)
                self.assertEqual(self.run_files(), self.packaged)
                self.assertNotIn('T6050', done.stderr)

    def test_no_device_tree_keeps_the_packaged_defaults(self):
        done = self.run_load_driver()
        self.assert_loaded_once_with(done, WRITES_ON)
        self.assertEqual(self.run_files(), self.packaged)
        self.assertEqual(done.stderr.count('\n'), 1, done.stderr)
        self.assertIn('enabled no SEP', done.stderr)

    def test_other_options_go_in_a_file_of_their_own(self):
        # The xart_guard opt-out that aurora-sep-ready names, beside the
        # read-only default.
        self.mac()
        self.install('etc/modprobe.d/aurora-sep-guard.conf', 'options apple_sep xart_guard=0\n')
        done = self.run_load_driver()
        self.assert_loaded_once_with(done, READ_ONLY + ['xart_guard=0'])


class T6050OwnerFileTest(LoadDriverCase):
    def test_the_owner_opts_in_with_the_etc_file(self):
        self.mac()
        self.install('etc/modprobe.d/aurora-sep.conf', OWNER_ON)
        done = self.run_load_driver()
        self.assert_loaded_once_with(done, WRITES_ON)
        self.assertEqual(self.run_files(), self.packaged)
        self.assertIn('/etc/modprobe.d/aurora-sep.conf sets', done.stderr)

    def test_other_owner_files_that_set_both(self):
        for text, given in (
                ('options apple_sep xart_writes=0 provision_keybag=0\n', READ_ONLY),
                ('options apple_sep xart_writes=1 provision_keybag=0\n',
                 ['xart_writes=1', 'provision_keybag=0']),
                ('options apple_sep xart_guard=0\n' + OWNER_ON, WRITES_ON + ['xart_guard=0']),
                # The kernel reads '-' as '_'.
                ('options apple_sep xart-writes=1 provision-keybag=1\n',
                 ['xart-writes=1', 'provision-keybag=1'])):
            with self.subTest(text=text):
                self.setUp()
                self.mac()
                self.install('etc/modprobe.d/aurora-sep.conf', text)
                self.assert_loaded_once_with(self.run_load_driver(), given)

    def test_the_etc_file_replaces_the_read_only_file_too(self):
        # Written earlier this boot, before the owner's file appeared.
        self.mac()
        self.install('run/modprobe.d/aurora-sep.conf',
                     'options apple_sep xart_writes=0 provision_keybag=0\n')
        self.install('etc/modprobe.d/aurora-sep.conf', OWNER_ON)
        self.assert_loaded_once_with(self.run_load_driver(), WRITES_ON)

    def test_a_wrong_owner_file_stops_the_load(self):
        for case, text in WRONG_OWNER_FILES.items():
            with self.subTest(case):
                self.setUp()
                self.mac()
                self.install('etc/modprobe.d/aurora-sep.conf', text)
                self.assert_not_loaded(self.run_load_driver(), 'not loading apple_sep')

    def test_other_macs_load_whatever_the_owner_file_says(self):
        self.mac('j815', 't8142')
        self.install('etc/modprobe.d/aurora-sep.conf', '')
        self.assert_loaded_once_with(self.run_load_driver(), [])


class T6050FailClosedTest(LoadDriverCase):
    def test_a_second_setting_stops_the_load(self):
        # Under another name the owner's line comes on top of the read-only
        # one; the kernel would refuse the driver, so load-driver does not
        # load it.
        self.mac()
        self.install('etc/modprobe.d/local.conf', 'options apple_sep xart_writes=1\n')
        self.assert_not_loaded(self.run_load_driver(),
                               "modprobe would give apple_sep 'provision_keybag=0 xart_writes=0 "
                               "xart_writes=1'")

    def test_settings_that_hide_writes_stop_the_load(self):
        for case, files in HIDDEN_WRITES.items():
            with self.subTest(case):
                self.setUp()
                self.mac()
                for name, text in files.items():
                    self.install(name, text)
                self.assert_not_loaded(self.run_load_driver(), 'not loading apple_sep')

    def test_a_link_from_the_owner_path_to_a_file_is_the_file(self):
        self.mac()
        self.install('etc/aurora/sep.conf', OWNER_ON)
        self.install('etc/modprobe.d/aurora-sep.conf', ('link', '../aurora/sep.conf'))
        self.assert_loaded_once_with(self.run_load_driver(), WRITES_ON)

    def test_kmod_not_reading_the_read_only_file_stops_the_load(self):
        self.mac()
        self.env['SKIP_RUN'] = '1'
        # What kmod then gives is whatever else it reads: the packaged
        # defaults, or on NixOS (whose defaults are in /run too) nothing.
        self.assert_not_loaded(self.run_load_driver(), "not 'xart_writes=0 provision_keybag=0'",
                               'not loading apple_sep')

    def test_the_kernel_command_line_counts(self):
        for files, cmdline, ok in (
                # The rig's read-only command line, on top of the default.
                ({}, 'xart_writes=0 provision_keybag=0', False),
                ({}, 'xart-writes=1', False),
                ({}, '--', False),
                ({'aurora-sep.conf': OWNER_ON}, 'xart_writes=1', False),
                ({}, 'xart_guard=0', True)):
            with self.subTest(cmdline=cmdline, files=files):
                self.setUp()
                self.mac()
                for name, text in files.items():
                    self.install(f'etc/modprobe.d/{name}', text)
                self.env['KCMDLINE'] = cmdline
                done = self.run_load_driver()
                if ok:
                    self.assert_loaded_once_with(done, READ_ONLY + cmdline.split())
                else:
                    self.assert_not_loaded(done, 'not loading')

    def test_a_read_only_file_it_cannot_write_stops_the_load(self):
        self.mac()
        # Not writable even for root.
        (self.root / 'run/modprobe.d/aurora-sep.conf.new').mkdir(parents=True)
        self.assert_not_loaded(self.run_load_driver(),
                               'not loading apple_sep, whose defaults turn SEP writes on')

    def test_a_driver_already_loaded_read_only_goes_on(self):
        self.mac()
        self.install('sys/module/apple_sep/parameters/keystore_only', '0\n')
        self.sep_device(policy='xart_writes=0 provision_keybag=0 xart_guard=1 trusted_keys=1')
        done = self.run_load_driver()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('apple_sep was already loaded, read-only', done.stderr)
        self.assertNotIn('SEP writes are off by default', done.stderr)

    def test_a_driver_already_loaded_otherwise_stops_it(self):
        for diag in ({'policy': 'xart_writes=1 provision_keybag=1 xart_guard=1'},
                     {'policy': 'xart_writes=0 provision_keybag=1 xart_guard=1'}, {}):
            with self.subTest(diag=diag):
                self.setUp()
                self.mac()
                self.install('sys/module/apple_sep/parameters/keystore_only', '0\n')
                self.sep_device(**diag)
                self.assert_not_loaded(self.run_load_driver(), 'reboot to load it read-only')
                self.assertEqual(self.probes(), [])


class T6050KeybagTest(LoadDriverCase):
    """With provisioning off no keybag appears, so there is nothing to seal a
    trusted key under: load-driver ends there without a failure, and
    aurora-sep-ready (Requires= this service) then reports Touch ID as not
    set up."""

    def test_a_default_t6050_without_a_keybag_ends_cleanly(self):
        self.mac()
        self.sep_device()
        done = self.run_load_driver()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.probes(), [])
        self.assertIn('provisions no identity keybag while SEP writes are off', done.stderr)

    def test_an_owner_file_without_provisioning_ends_cleanly(self):
        for text in ('options apple_sep xart_writes=0 provision_keybag=0\n',
                     'options apple_sep xart_writes=1 provision_keybag=0\n'):
            with self.subTest(text=text):
                self.setUp()
                self.mac()
                self.install('etc/modprobe.d/aurora-sep.conf', text)
                self.sep_device()
                done = self.run_load_driver()
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(self.probes(), [])

    def test_a_t6050_with_a_keybag_probes_it(self):
        # One kept from an earlier opt-in: read-only trusted keys may work.
        self.mac()
        self.install('var/lib/aurora-sep-keybag.bin', 'bag')
        self.install('var/lib/aurora-sep-refkey.bin', 'key')
        self.sep_device()
        done = self.run_load_driver()
        self.assertEqual(done.returncode, 1)
        self.assertEqual(len(self.probes()), 1)
        self.assertIn('did not seal and unseal', done.stderr)

    def test_provisioning_on_still_probes(self):
        for board, soc, owner in (('j714s', 't6050', OWNER_ON), ('j815', 't8142', None)):
            with self.subTest(soc=soc):
                self.setUp()
                self.mac(board, soc)
                if owner:
                    self.install('etc/modprobe.d/aurora-sep.conf', owner)
                self.sep_device()
                done = self.run_load_driver()
                self.assertEqual(done.returncode, 1)
                self.assertEqual(len(self.probes()), 1)
                self.assertNotIn('provisions no identity keybag', done.stderr)


class T6050InitrdAttachTest(LoadDriverCase):
    """The initrd loads apple_sep with the options it carries, before
    load-driver runs; on a T6050 load-driver finishes that attach only when
    the owner's file sets both options."""

    def setUp(self):
        super().setUp()
        self.install('sys/module/apple_sep/parameters/keystore_only', '1\n')
        self.attr = self.root / 'sys/bus/platform/drivers/apple_sep/2c3800000.sep/complete_attach'
        self.install(self.attr.relative_to(self.root), '')

    def finish(self):
        done = self.run_load_driver()
        self.assertEqual(self.loads(), [], 'modprobe loaded the driver')
        return done, self.attr.read_text()

    def test_a_t6050_leaves_the_attach_unfinished(self):
        self.mac()
        done, written = self.finish()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(written, '')
        self.assertIn('the attach the initrd started stays unfinished', done.stderr)

    def test_a_t6050_without_a_keybag_then_ends_cleanly(self):
        self.mac()
        self.sep_device()
        done, written = self.finish()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(written, '')
        self.assertEqual(self.probes(), [])

    def test_a_t6050_whose_owner_set_the_options_finishes_it(self):
        self.mac()
        self.install('etc/modprobe.d/aurora-sep.conf', OWNER_ON)
        done, written = self.finish()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(written, '1\n')
        self.assertIn('finished the attach the initrd started', done.stderr)

    def test_a_read_only_owner_file_leaves_it_unfinished(self):
        # The initrd's own options may be the kernel's writes-on defaults (on
        # NixOS they always are), and finishing would reopen xART with them.
        for text in ('options apple_sep xart_writes=0 provision_keybag=0\n',
                     'options apple_sep xart_writes=1 provision_keybag=0\n',
                     'options apple_sep xart_guard=0 xart_writes=0 provision_keybag=0\n'):
            with self.subTest(text=text):
                self.setUp()
                self.mac()
                self.install('etc/modprobe.d/aurora-sep.conf', text)
                self.sep_device()
                done, written = self.finish()
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(written, '')
                self.assertIn('only /', done.stderr)
                self.assertIn('the attach the initrd started stays unfinished', done.stderr)
                # Nothing to probe without a keybag.
                self.assertEqual(self.probes(), [])

    def test_something_else_at_the_owner_path_leaves_it_unfinished(self):
        for text in (('dir', None), ('link', '/dev/null'), ('link', '/nonexistent.conf')):
            with self.subTest(text=text):
                self.setUp()
                self.mac()
                self.install('etc/modprobe.d/aurora-sep.conf', text)
                done, written = self.finish()
                self.assertEqual(done.returncode, 1)
                self.assertEqual(written, '')
                self.assertIn('is not a regular file', done.stderr)

    def test_a_wrong_owner_file_leaves_it_unfinished(self):
        for case, text in WRONG_OWNER_FILES.items():
            with self.subTest(case):
                self.setUp()
                self.mac()
                self.install('etc/modprobe.d/aurora-sep.conf', text)
                done, written = self.finish()
                self.assertEqual(done.returncode, 1)
                self.assertEqual(written, '')
                self.assertIn('not finishing the attach the initrd started', done.stderr)

    def test_other_macs_finish_it(self):
        self.mac('j815', 't8142')
        done, written = self.finish()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(written, '1\n')
        self.assertIn('finished the attach the initrd started', done.stderr)


if __name__ == '__main__':
    unittest.main()
