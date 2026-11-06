"""Exercise configured Steam packages through their real FHS and native loop."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

CONFIG = json.loads(Path(sys.argv.pop(1)).read_text())
# GitHub ARM runners execute the VM under TCG, including the first writable
# copy of the real Proton tree. Native/KVM timings don't represent that cost.
LAUNCH_TIMEOUT = 300


class InstalledSteamRuntime(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory())) / 'home with spaces'
        self.home.mkdir()
        self.data = self.home / 'data with spaces'
        self.prefix = self.home / 'Steam prefix'
        binary = self.prefix / 'steamrtarm64/steam'
        binary.parent.mkdir(parents=True)
        shutil.copyfile(CONFIG['payload'], binary)
        binary.chmod(0o755)
        self.report = self.home / 'report.jsonl'

    def prepared(self):
        return self.data / 'aurora-proton' / Path(CONFIG['proton']).name

    def launch(self, package='default', compatibility=None, statuses=(0,), expected=0):
        self.report.unlink(missing_ok=True)
        env = os.environ.copy()
        for key in ('STEAM_EXTRA_COMPAT_TOOLS_PATHS', 'AURORA_STEAM_LIBEXEC',
                    'AURORA_STEAM_CONFIGURED', 'SDL_JOYSTICK_DISABLE_UDEV'):
            env.pop(key, None)
        env.update({
            'HOME': str(self.home), 'USER': 'fixture', 'XDG_DATA_HOME': str(self.data),
            'AURORA_STEAM_ROOT': str(self.prefix), 'AURORA_USERPAGES_LAUNCHER': CONFIG['pageLauncher'],
            'AURORA_STEAM_CONSOLE_LOG': str(self.home / 'console.log'),
            'AURORA_STEAM_RESTART_LIMIT': '1', 'AURORA_TEST_STEAM_PROBE': CONFIG['probe'],
            'AURORA_TEST_REPORT': str(self.report), 'AURORA_TEST_EXPECTED_COMPAT': json.dumps(compatibility),
            'AURORA_TEST_EXIT_CODES': json.dumps(statuses),
        })
        if package == 'runtime-custom':
            env['STEAM_EXTRA_COMPAT_TOOLS_PATHS'] = compatibility
        executable = CONFIG['packages']['default' if package == 'runtime-custom' else package] + '/bin/steam'
        log = self.home / 'console.log'
        with subprocess.Popen([executable, 'argument with spaces'], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, start_new_session=True) as process:
            try:
                stdout, stderr = process.communicate(timeout=LAUNCH_TIMEOUT)
            except subprocess.TimeoutExpired:
                # Killing just the launcher leaves its copy/sandbox workers
                # writing into TemporaryDirectory while unittest removes it.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, stderr = process.communicate()
                self.fail(f'Steam launcher exceeded {LAUNCH_TIMEOUT} seconds\n'
                          + stdout + stderr + (log.read_text() if log.exists() else ''))
            self.assertEqual(process.returncode, expected,
                             stdout + stderr + (log.read_text() if log.exists() else ''))
        rows = [json.loads(line) for line in self.report.read_text().splitlines()]
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row['argv'], ['-beta', 'publicbeta', 'argument with spaces'])
            self.assertEqual(row['compat'], compatibility)
            self.assertEqual(row['pages'], 4096)
        return rows

    def test_default_tool_is_prepared_and_user_settings_survive_relaunch(self):
        tool = self.prepared()
        self.launch(compatibility=str(tool))
        self.assertEqual((tool / '.aurora-proton-source').read_text().strip(), CONFIG['proton'])
        self.assertTrue((tool / 'proton').stat().st_mode & 0o200)
        settings = tool / 'user_settings.py'
        settings.write_text('user_settings = {"PROTON_LOG": "1"}\n')
        self.launch(compatibility=str(tool))
        self.assertEqual(settings.read_text(), 'user_settings = {"PROTON_LOG": "1"}\n')

    def test_runtime_custom_paths_take_precedence_without_preparing_default(self):
        compatibility = f'{self.home}/my tool:{self.home}/other tool'
        self.launch(package='runtime-custom', compatibility=compatibility)
        self.assertFalse((self.data / 'aurora-proton').exists())

    def test_module_extra_compat_packages_reach_the_installed_launcher(self):
        self.launch(package='configured-custom', compatibility=CONFIG['configuredCompat'])
        self.assertFalse((self.data / 'aurora-proton').exists())

    def test_disabling_bundled_proton_omits_both_copy_and_environment(self):
        self.launch(package='disabled')
        self.assertFalse((self.data / 'aurora-proton').exists())

    def test_restart_request_stays_inside_fhs_and_preserves_arguments(self):
        rows = self.launch(package='disabled', statuses=(42, 0))
        self.assertEqual(len(rows), 2)

    def test_native_failure_propagates_to_the_public_launcher(self):
        self.launch(package='disabled', statuses=(7,), expected=7)


if __name__ == '__main__':
    unittest.main()
