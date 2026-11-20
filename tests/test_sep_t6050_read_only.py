"""The M5 Pro and Max (T6050) load apple_sep with SEP writes off by default.

xART is shared with macOS, and its write paths (keybag provisioning, Touch
ID enrolment) have had no trial on a T6050. So on a device tree that names
apple,t6050, load-driver puts "xart_writes=0 provision_keybag=0" in
/run/modprobe.d/aurora-sep.conf, which stands in for the packaged defaults,
unless the owner's /etc/modprobe.d/aurora-sep.conf sets the options. Every
other Mac keeps the packaged defaults. The kernel (7.3.0-41, 7.3.0-43)
refuses a second value of an apple_sep parameter and does not load the
driver, so each must reach it exactly once; load-driver checks what kmod
will pass and does not load the driver otherwise.

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
# kmod's search order: a file hides one of the same name further down.
DIRS = ('etc/modprobe.d', 'run/modprobe.d', 'usr/lib/modprobe.d')
KMOD = shutil.which('modprobe', path=os.environ.get('PATH', '') + ':/usr/sbin:/sbin')

READ_ONLY = ['xart_writes=0', 'provision_keybag=0']
WRITES_ON = ['xart_writes=1', 'provision_keybag=1']
OWNER_ON = 'options apple_sep xart_writes=1 provision_keybag=1\n'

T6050_BOARDS = ('j714s', 'k116s', 'j716c')
OTHER_MACS = (('j815', 't8142'), ('j614c', 't6041'), ('j616s', 't6040'), ('j700', 't8140'),
              ('j713', 't8132'), ('j414s', 't6020'), ('j293', 't8103'))

# -c prints the configuration kmod reads from the test's root (the kernel
# command line included); anything else is a load, logged with the apple_sep
# options kmod would pass.
MODPROBE = r'''#!/bin/sh
set -- "$@" --
for d in etc/modprobe.d run/modprobe.d usr/lib/modprobe.d; do
    [ -d "$TEST_ROOT/$d" ] && set -- "$@" "--config=$TEST_ROOT/$d"
done
args=
while [ "$1" != -- ]; do args="$args $1"; shift; done
shift
if [ "$args" = " -c" ]; then
    exec "$KMOD" "$@" -c
fi
echo "load$args" >>"$MODPROBE_LOG"
"$KMOD" "$@" -c | sed -n 's/^options apple_sep /options /p' >>"$MODPROBE_LOG"
'''


def compatible(board, soc):
    return f'apple,{board}\0apple,{soc}\0apple,arm-platform\0'


@unittest.skipUnless(KMOD, 'needs kmod')
class T6050ReadOnlyTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        tmp = Path(temporary.name)
        self.root = tmp / 'root'
        self.install(DEFAULTS, (SEP / 'aurora-sep-modprobe.conf').read_text())
        self.install(*BLACKLIST)
        (self.root / 'etc/modprobe.d').mkdir(parents=True, exist_ok=True)
        # No *.sep device: load-driver stops after loading the driver.
        sysfs = tmp / 'devices'
        sysfs.mkdir()
        bin_dir = tmp / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'modprobe').write_text(MODPROBE)
        (bin_dir / 'modprobe').chmod(0o755)
        self.log = tmp / 'modprobe.log'
        self.log.touch()
        self.packaged = self.run_files()
        self.env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}',
                        AURORA_SEP_SESSION='1', AURORA_SEP_SYSFS=str(sysfs),
                        AURORA_SEP_ROOT=str(self.root), TEST_ROOT=str(self.root),
                        KMOD=KMOD, MODPROBE_LOG=str(self.log))

    def install(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

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

    def assert_loaded_once_with(self, done, options):
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.loads()), 1, done.stderr)
        argv, given = self.loads()[0]
        self.assertEqual(argv, ['apple_sep'])
        # Each parameter once: a second value fails the load.
        self.assertCountEqual(given, options)

    def test_a_t6050_loads_the_driver_read_only(self):
        for board in T6050_BOARDS:
            with self.subTest(board=board):
                self.setUp()
                self.install('proc/device-tree/compatible', compatible(board, 't6050'))
                done = self.run_load_driver()
                self.assert_loaded_once_with(done, READ_ONLY)
                self.assertEqual(self.run_files(), {
                    'aurora-sep.conf': 'options apple_sep xart_writes=0 provision_keybag=0\n'})
                self.assertIn('SEP writes are off by default on this Mac (T6050)', done.stderr)

    def test_other_macs_keep_the_packaged_defaults(self):
        for board, soc in OTHER_MACS:
            with self.subTest(soc=soc):
                self.setUp()
                self.install('proc/device-tree/compatible', compatible(board, soc))
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

    def test_the_owner_opts_in_with_the_etc_file(self):
        self.install('proc/device-tree/compatible', compatible('j714s', 't6050'))
        self.install('etc/modprobe.d/aurora-sep.conf', OWNER_ON)
        done = self.run_load_driver()
        self.assert_loaded_once_with(done, WRITES_ON)
        self.assertEqual(self.run_files(), self.packaged)
        self.assertIn('/etc/modprobe.d/aurora-sep.conf sets', done.stderr)

    def test_the_etc_file_replaces_the_read_only_file_too(self):
        # Written earlier this boot, before the owner's file appeared.
        self.install('proc/device-tree/compatible', compatible('j714s', 't6050'))
        self.install('run/modprobe.d/aurora-sep.conf',
                     'options apple_sep xart_writes=0 provision_keybag=0\n')
        self.install('etc/modprobe.d/aurora-sep.conf', OWNER_ON)
        done = self.run_load_driver()
        self.assert_loaded_once_with(done, WRITES_ON)

    def test_a_second_setting_stops_the_load(self):
        # Under another name the owner's line comes on top of the read-only
        # one; the kernel would refuse the driver, so load-driver does not
        # load it.
        self.install('proc/device-tree/compatible', compatible('j714s', 't6050'))
        self.install('etc/modprobe.d/local.conf', 'options apple_sep xart_writes=1\n')
        done = self.run_load_driver()
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.loads(), [])
        self.assertIn("modprobe would give apple_sep 'provision_keybag=0 xart_writes=0 "
                      "xart_writes=1'", done.stderr)

    def test_a_read_only_file_it_cannot_write_stops_the_load(self):
        self.install('proc/device-tree/compatible', compatible('j714s', 't6050'))
        # Not writable even for root.
        (self.root / 'run/modprobe.d/aurora-sep.conf.new').mkdir(parents=True)
        done = self.run_load_driver()
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.loads(), [])
        self.assertIn('not loading apple_sep, whose defaults turn SEP writes on', done.stderr)


class T6050InitrdAttachTest(unittest.TestCase):
    """The initrd loads apple_sep with the options it carries, before
    load-driver runs; on a T6050 load-driver finishes that attach only when
    the owner set the options."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        tmp = Path(temporary.name)
        self.root = tmp / 'root'
        self.install('sys/module/apple_sep/parameters/keystore_only', '1\n')
        self.install('sys/bus/platform/drivers/apple_sep/2c3800000.sep/complete_attach', '')
        sysfs = tmp / 'devices'
        sysfs.mkdir()
        bin_dir = tmp / 'bin'
        bin_dir.mkdir()
        self.log = tmp / 'modprobe.log'
        (bin_dir / 'modprobe').write_text(f'#!/bin/sh\necho "$*" >>{shlex.quote(str(self.log))}\n')
        (bin_dir / 'modprobe').chmod(0o755)
        self.env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}',
                        AURORA_SEP_SESSION='1', AURORA_SEP_SYSFS=str(sysfs),
                        AURORA_SEP_ROOT=str(self.root))

    def install(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def complete_attach(self):
        done = subprocess.run(['sh', str(LOAD_DRIVER)], env=self.env, capture_output=True,
                              text=True, check=False, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(self.log.exists(), 'modprobe ran')
        attr = self.root / 'sys/bus/platform/drivers/apple_sep/2c3800000.sep/complete_attach'
        return attr.read_text(), done.stderr

    def test_a_t6050_leaves_the_attach_unfinished(self):
        self.install('proc/device-tree/compatible', compatible('j714s', 't6050'))
        written, stderr = self.complete_attach()
        self.assertEqual(written, '')
        self.assertIn('its attach stays unfinished', stderr)

    def test_a_t6050_whose_owner_set_the_options_finishes_it(self):
        self.install('proc/device-tree/compatible', compatible('j714s', 't6050'))
        self.install('etc/modprobe.d/aurora-sep.conf', OWNER_ON)
        written, stderr = self.complete_attach()
        self.assertEqual(written, '1\n')
        self.assertIn('finished the attach the initrd started', stderr)

    def test_other_macs_finish_it(self):
        self.install('proc/device-tree/compatible', compatible('j815', 't8142'))
        written, stderr = self.complete_attach()
        self.assertEqual(written, '1\n')
        self.assertIn('finished the attach the initrd started', stderr)


if __name__ == '__main__':
    unittest.main()
