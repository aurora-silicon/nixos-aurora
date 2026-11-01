# SPDX-License-Identifier: GPL-2.0-only
"""Exercise generated overlays against public GNOME Shell JS sources.

Usage: python3 test_greeter.py /path/to/gnome-shell/js/gdm [JS_RUNTIME]
JS_RUNTIME is node or JavaScriptCore's jsc. No root, device or D-Bus required.
"""
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parent
SOURCE = Path(sys.argv[1])
RUNTIME = sys.argv[2] if len(sys.argv) > 2 else shutil.which('node')
sys.argv[1:] = []
GENERATOR = (PACKAGE / 'aurora-sep-greeter-fingerprint').read_text().split("<<'PYTHON'\n", 1)[1].split('\nPYTHON\n', 1)[0]


def generate(directory, auth=None, manager=None):
    (directory / 'stock-auth.js').write_text(auth or (SOURCE / 'authServicesLegacy.js').read_text())
    (directory / 'stock-manager.js').write_text(manager or (SOURCE / 'fingerprintManager.js').read_text())
    return subprocess.run([sys.executable, '-c', GENERATOR, str(directory)], capture_output=True, text=True)


def module(source):
    return re.sub(r'^import .*;\n', '', source, flags=re.M).replace('export ', '')


class GreeterTests(unittest.TestCase):
    def test_unexpected_sources_publish_neither_overlay(self):
        stock_auth = (SOURCE / 'authServicesLegacy.js').read_text()
        stock_manager = (SOURCE / 'fingerprintManager.js').read_text()
        for auth, manager in [
            (stock_auth.replace('if (!this._reauthOnly)', 'if (false)'), stock_manager),
            (stock_auth, stock_manager.replace('await this.checkReaderType();', 'await changed();')),
            (stock_auth + stock_auth, stock_manager),
        ]:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)
                self.assertNotEqual(generate(path, auth, manager).returncode, 0)
                self.assertFalse((path / 'authServicesLegacy.js').exists())
                self.assertFalse((path / 'fingerprintManager.js').exists())

    def test_late_restore_and_authentication(self):
        self.assertTrue(RUNTIME, 'Pass node or jsc as JS_RUNTIME')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            result = generate(path)
            self.assertEqual(result.returncode, 0, result.stderr)
            # Run actual patched modules plus stock AuthServices. Only GI, D-Bus,
            # the file monitor and GDM's PAM endpoint are mocked by the harness.
            harness = (PACKAGE / 'test_greeter.js').read_text()
            harness = harness.replace('@MANAGER@', module((path / 'fingerprintManager.js').read_text()))
            harness = harness.replace('@AUTH@', module((SOURCE / 'authServices.js').read_text()))
            harness = harness.replace('@LEGACY@', module((path / 'authServicesLegacy.js').read_text()))
            (path / 'test.js').write_text(harness)
            result = subprocess.run([RUNTIME, str(path / 'test.js')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS: late reader', result.stdout, result.stdout + result.stderr)
            print(result.stdout.strip())

    @unittest.skipUnless(shutil.which('glib-compile-resources') and shutil.which('gresource'), 'GLib tools required')
    def test_resource_extraction_and_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            xml = path / 'fixture.xml'
            xml.write_text('<gresources><gresource prefix="/org/gnome/shell/gdm">'
                           '<file>authServicesLegacy.js</file><file>fingerprintManager.js</file>'
                           '</gresource></gresources>')
            lib = path / 'libshell-fixture.so'
            subprocess.run(['glib-compile-resources', str(xml), '--target', str(lib),
                            '--sourcedir', str(SOURCE.resolve())], check=True)
            out, dropin = path / 'overlay', path / 'service.d/fingerprint.conf'
            script = (PACKAGE / 'aurora-sep-greeter-fingerprint').read_text()
            script = script.replace('out=/run/aurora-sep/greeter', 'out=' + shlex.quote(str(out)))
            script = script.replace('dropin=/run/systemd/user/org.gnome.Shell@gdm.service.d/aurora-sep-fingerprint.conf',
                                    'dropin=' + shlex.quote(str(dropin)))
            script = re.sub(r'for f in /usr/lib64.*?; do', 'for f in ' + shlex.quote(str(lib)) + '; do', script, flags=re.S)
            helper = path / 'helper'
            helper.write_text(script)
            result = subprocess.run(['sh', str(helper)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = ':'.join(f'/org/gnome/shell/gdm/{name}={out}/{name}'
                                for name in ['authServicesLegacy.js', 'fingerprintManager.js'])
            self.assertEqual(dropin.read_text(), '[Service]\nEnvironment=G_RESOURCE_OVERLAYS=' + expected + '\n')
            subprocess.run(['sh', str(helper), 'stop'], check=True)
            self.assertFalse(out.exists())
            self.assertFalse(dropin.exists())

    @unittest.skipUnless(Path('/proc/uptime').exists(), 'readiness helper uses Linux uptime')
    def test_readiness_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            diag = root / 'devices/fixture.sep/diag'
            diag.mkdir(parents=True)
            run = root / 'run'
            run.mkdir()
            marker = run / 'reader-restored'
            env = dict(os.environ, AURORA_SEP_SYSFS=str(root / 'devices'),
                       AURORA_SEP_RUN=str(run), AURORA_SEP_DEV='/dev/null')
            for name, value in {'touchid': 'ready', 'sensor_attach': 'attached', 'restore': 'restored'}.items():
                (diag / name).write_text(value + '\n')
            for matching, expected in [('usable', True), ('unverified', True), ('blocked', False)]:
                (diag / 'matching').write_text(matching + '\n')
                marker.touch()  # A stale success must not survive a failed retry.
                result = subprocess.run(['sh', str(PACKAGE / 'aurora-sep-ready')], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0 if expected else 1, result.stderr)
                self.assertEqual(marker.exists(), expected)
                if expected:
                    self.assertEqual(marker.read_bytes(), b'')
                    self.assertEqual(marker.stat().st_mode & 0o777, 0o644)
            (diag / 'matching').write_text('usable\n')
            (diag / 'restore').write_text('unproven\n')
            marker.touch()
            result = subprocess.run(['sh', str(PACKAGE / 'aurora-sep-ready')], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
