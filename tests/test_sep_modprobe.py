"""SEP writes are always on. apple_sep has no xart_writes or provision_keybag
parameter (aurora-silicon/linux#2591), and nothing this repository configures
sets one: no modprobe.d file, no modprobe command line, no kernel command
line. With no packaged value, a parameter can no longer reach the driver
twice, which stopped older kernels loading it (nixos-aurora#354)."""
from pathlib import Path
import re
import shlex
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SEP = ROOT / 'sep'
REMOVED = ('xart_writes', 'provision_keybag')
_names = '|'.join(REMOVED)
# A modprobe.d options line, a modprobe command line or a kernel command line
# that gives apple_sep one of the removed parameters.
SETS = re.compile(rf'^\s*options\s+apple_sep\b.*\b(?:{_names})\b'
                  rf'|\bmodprobe(?:\s+-\S+)*\s+apple_sep\b[^;|&"\n]*\b(?:{_names})='
                  rf'|\bapple_sep\.(?:{_names})=', re.M)


def tracked_files():
    try:
        out = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z'],
                             capture_output=True, check=True).stdout.decode()
        names = [n for n in out.split('\0') if n]
    except (OSError, subprocess.CalledProcessError):
        names = [str(p.relative_to(ROOT)) for p in ROOT.rglob('*')
                 if p.is_file() and '.git' not in p.parts]
    for name in names:
        path = ROOT / name
        if path.parts[len(ROOT.parts)] == 'tests' or not path.is_file():
            continue
        yield path


def text_of(path):
    try:
        return path.read_text()
    except UnicodeDecodeError:
        return ''


class SepWritesAlwaysOnTests(unittest.TestCase):
    def test_nothing_shipped_sets_a_removed_parameter(self):
        found = [f'{path.relative_to(ROOT)}: {m.group(0).strip()}'
                 for path in tracked_files() for m in SETS.finditer(text_of(path))]
        self.assertEqual(found, [])

    def test_no_module_configures_an_apple_sep_write_option(self):
        modules = sorted((ROOT / 'modules').rglob('*.nix'))
        self.assertTrue(modules)
        for nix in [*modules, *ROOT.glob('*.nix')]:
            with self.subTest(module=str(nix.relative_to(ROOT))):
                for name in REMOVED:
                    self.assertNotIn(name, nix.read_text())

    def test_the_sep_module_ships_no_modprobe_options(self):
        module = (ROOT / 'modules/sep.nix').read_text()
        # The load-ordering blacklist stays: aurora-sep.service loads the driver.
        self.assertIn('boot.blacklistedKernelModules = [ "apple_sep" ];', module)
        self.assertNotIn('modprobe.d', module)
        self.assertNotIn('extraModprobeConfig', module)
        self.assertNotIn('aurora-sep-modprobe.conf', module)
        self.assertFalse((SEP / 'aurora-sep-modprobe.conf').exists())

    def test_ci_checks_the_evaluated_profiles(self):
        workflow = (ROOT / '.github/workflows/checks.yml').read_text()
        self.assertIn('Check that no profile sets an apple_sep write option', workflow)
        self.assertIn('"xart_writes|provision_keybag"', workflow)

    def test_load_driver_passes_no_options(self):
        text = (SEP / 'load-driver').read_text()
        calls = [w for w in map(lambda l: shlex.split(l, comments=True), text.splitlines())
                 if w[:1] == ['modprobe'] and 'apple_sep' in w]
        self.assertEqual(calls, [['modprobe', 'apple_sep']])
        for name in REMOVED:
            self.assertNotIn(name, text)

    def test_messages_name_no_off_switch(self):
        status = (SEP / 'aurora-sep').read_text()
        ready = (SEP / 'aurora-sep-ready').read_text()
        for text in (status, ready):
            for name in REMOVED:
                self.assertNotIn(f'{name}=0', text)
        self.assertIn('"xART writes are disabled: the store is read-only this boot', status)
        self.assertIn('echo "xART writes are disabled (the store is read-only this boot', ready)
        # checks/sep-lifecycle.py looks for that reason in the journal.
        lifecycle = (ROOT / 'checks/sep-lifecycle.py').read_text()
        self.assertIn("grep -F 'xART writes are disabled'", lifecycle)


if __name__ == '__main__':
    unittest.main()
