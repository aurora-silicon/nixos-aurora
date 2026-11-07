import os
import shutil
import subprocess
import tempfile
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


if __name__ == "__main__":
    unittest.main()
