import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SteamWrapperTests(unittest.TestCase):
    def test_runtime_launcher_path(self):
        for custom_root in (False, True):
            with self.subTest(
                custom_root=custom_root
            ), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                home = base / "home"
                prefix = base / "Steam prefix with spaces"
                runtime = (
                    prefix
                    / "steamapps/common/SteamLinuxRuntime_4-arm64/pressure-vessel/bin"
                )
                lib = base / "lib"
                bash = shutil.which("bash")
                self.assertIsNotNone(bash)

                def executable(path, body):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"#!{bash}\nset -eu\n{body}\n")
                    path.chmod(0o755)

                executable(prefix / "steamrtarm64/steam", "exit 0")
                executable(runtime / "steam-runtime-launcher-service", "exit 0")
                executable(base / "userpages", 'test "$1" = 4k; shift; exec "$@"')
                executable(
                    lib / "bin/steam-native4k",
                    'command -v steam-runtime-launcher-service\nprintf "%s\\n" "$@"',
                )
                (home / ".steam").mkdir(parents=True)
                (home / ".steam/root").symlink_to(prefix)

                wrapper = base / "steam"
                wrapper.write_text(
                    (ROOT / "steam/steam")
                    .read_text()
                    .replace("@LIBDIR@", str(lib))
                    .replace("@USERPAGES@", str(base / "userpages"))
                    .replace("@USER4K_HINT@", "fixture")
                )
                env = os.environ.copy()
                env.pop("AURORA_STEAM_ROOT", None)
                env.pop("AURORA_USERPAGES_LAUNCHER", None)
                env["HOME"] = str(home)
                if custom_root:
                    env["AURORA_STEAM_ROOT"] = str(prefix)
                    (home / ".steam/root").unlink()
                result = subprocess.run(
                    [bash, str(wrapper), "argument with spaces"],
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = result.stdout.splitlines()
                self.assertEqual(len(lines), 2)
                self.assertEqual(
                    Path(lines[0]).resolve(), runtime / "steam-runtime-launcher-service"
                )
                self.assertEqual(lines[1], "argument with spaces")

    def test_nixos_bootstrap_uses_system_launchers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, lib = root / 'home', root / 'lib'
            home.mkdir()
            (lib / 'bin').mkdir(parents=True)
            bash = shutil.which('bash')
            userpages = root / 'userpages'
            userpages.write_text(f'#!{bash}\nshift; exec "$@"\n')
            userpages.chmod(0o755)
            (lib / 'bin/steam-native4k').write_text(f'#!{bash}\nexit 0\n')
            (lib / 'bin/steam-native4k').chmod(0o755)
            (lib / 'install-steam-arm64.py').write_text(
                'import os\nfrom pathlib import Path\n'
                'assert os.environ["AURORA_SYSTEM_LAUNCHERS"] == "1"\n'
                'p = Path.home() / ".steam/root/steamrtarm64"\n'
                'p.mkdir(parents=True)\n'
                '(p / "steam").write_text("fixture")\n')
            wrapper = root / 'steam'
            wrapper.write_text((ROOT / 'steam/steam').read_text()
                .replace('@LIBDIR@', str(lib)).replace('@USERPAGES@', str(userpages))
                .replace('@USER4K_HINT@', 'fixture'))
            env = {**os.environ, 'HOME': str(home), 'USER': 'fixture'}
            env.pop('AURORA_STEAM_ROOT', None)
            env.pop('AURORA_USERPAGES_LAUNCHER', None)
            result = subprocess.run([bash, str(wrapper)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_steam_registers_each_game_process_with_gamemode(self):
        # The watcher follows the client's logs/gameprocess_log.txt through
        # inotify, registers every tracked PID and sleeps in between.
        def watchers(root):
            found = []
            for proc in Path('/proc').iterdir():
                try:
                    argv = (proc / 'cmdline').read_bytes().split(b'\0')
                except OSError:
                    continue
                if argv[0] == b'aurora-steam-gamemode' and str(root).encode() in b' '.join(argv):
                    found.append(proc)
            return found

        def wait(condition):
            deadline = time.monotonic() + 10
            while not condition():
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.05)

        def switches(proc):
            status = (proc / 'status').read_text()
            return int(re.search(r'(?m)^voluntary_ctxt_switches:\s+(\d+)$', status)[1])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lib, home, stubs, client = root / 'lib', root / 'home', root / 'stubs', root / 'client'
            for path in (lib / 'bin', client / 'steamrtarm64', client / 'logs', stubs, home / '.steam'):
                path.mkdir(parents=True)
            (home / '.steam/root').symlink_to(client)
            gamelog, log = client / 'logs/gameprocess_log.txt', root / 'busctl.log'
            gamelog.write_text('[2026-11-17 19:14:50] AppID 9 adding PID 999 as a tracked process\n')
            log.write_text('')
            bash = shutil.which('bash')

            def script(path, body):
                path.write_text(f'#!{bash}\n' + body)
                path.chmod(0o755)
            script(client / 'steamrtarm64/steam', '')
            script(lib / 'bin/steam-native4k', 'exec sleep 60\n')
            script(root / 'userpages', '')
            script(stubs / 'busctl', f'echo "busctl $*" >> {log}\n'
                   'case "$*" in *ListActivatableNames*) echo \'as 2 "org.freedesktop.DBus" "com.feralinteractive.GameMode"\';; esac\n')
            wrapper = root / 'steam'
            wrapper.write_text((ROOT / 'steam/steam').read_text().replace('@LIBDIR@', str(lib))
                               .replace('@USERPAGES@', str(root / 'userpages')).replace('@USER4K_HINT@', 'hint'))
            wrapper.chmod(0o755)
            env = {'HOME': str(home), 'PATH': f'{stubs}:{os.environ["PATH"]}', 'USER': 'test'}

            def registered():
                return [line.split()[-1] for line in log.read_text().splitlines() if 'RegisterGameByPID ii' in line]

            steam = subprocess.Popen([bash, str(wrapper)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                wait(lambda: len(watchers(client)) == 1)
                watcher = watchers(client)[0]
                wait(lambda: (watcher / 'stat').read_text().rsplit(')', 1)[1].split()[0] == 'S')
                with gamelog.open('a') as f:
                    f.write('[2026-11-20 10:00:00] AppID 383870 adding PID 4242 as a tracked process "x"\n'
                            '[2026-11-20 10:00:00] AppID 383870 adding PID 4243 as a')
                wait(lambda: registered() == ['4242'])
                with gamelog.open('a') as f:
                    f.write(' tracked process\n')
                wait(lambda: registered() == ['4242', '4243'])
                # Idle: blocked in select(), no wake-ups at all.
                time.sleep(0.5)
                before = switches(watcher)
                time.sleep(2)
                self.assertEqual(switches(watcher), before)
                # Steam rotates the log and starts a new one.
                gamelog.rename(gamelog.with_name('gameprocess_log.previous.txt'))
                gamelog.write_text('[2026-11-20 10:05:00] AppID 1 adding PID 5000 as a tracked process\n')
                wait(lambda: registered() == ['4242', '4243', '5000'])
                self.assertIn('busctl --user call com.feralinteractive.GameMode /com/feralinteractive/GameMode '
                              'com.feralinteractive.GameMode RegisterGameByPID ii', log.read_text())
            finally:
                steam.kill()
                steam.wait()
            # The watcher ends with Steam.
            wait(lambda: not watchers(client))
            # Opt-out: no watcher while Steam runs.
            steam = subprocess.Popen([bash, str(wrapper)], env={**env, 'AURORA_STEAM_GAMEMODE': '0'},
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                wait(lambda: (Path('/proc') / str(steam.pid) / 'cmdline').read_bytes().startswith(b'sleep'))
                time.sleep(0.5)
                self.assertEqual(watchers(client), [])
            finally:
                steam.kill()
                steam.wait()
            self.assertEqual(registered(), ['4242', '4243', '5000'])


if __name__ == "__main__":
    unittest.main()
