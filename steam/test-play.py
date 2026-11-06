#!/usr/bin/env python3
"""Exercise the patched Play launcher and native-tool discovery without a display."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

PLAY = Path(sys.argv.pop(1)).resolve()
NATIVE_TOOL = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 else None
sys.dont_write_bytecode = True


class PlayIntegration(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.steam = self.root / 'steam'
        self.tool = self.root / 'extra/GE-Proton-native'
        self.tool.mkdir(parents=True)
        (self.tool / 'proton').touch()
        (self.tool / 'files/bin').mkdir(parents=True)
        (self.tool / 'files/bin/wine').write_bytes(b'\x7fELF\x02\x01' + b'\0' * 12 + b'\xb7\0')
        self.launcher = self.root / 'public-steam'
        self.launcher.touch()
        self.enterContext(mock.patch.dict(os.environ, {
            'HOME': str(self.home), 'AURORA_STEAM_ROOT': str(self.steam),
            'AURORA_STEAM_LAUNCHER': str(self.launcher),
            'STEAM_EXTRA_COMPAT_TOOLS_PATHS': str(self.tool),
        }))
        gi = types.ModuleType('gi')
        gi.require_version = lambda *_: None
        repo = types.ModuleType('gi.repository')
        for name in ('Adw', 'Gdk', 'Gio', 'Gtk', 'Pango'):
            setattr(repo, name, types.SimpleNamespace(ApplicationWindow=object, Application=object, Button=object, Toast=lambda **kwargs: kwargs))
        gi.repository = repo
        self.enterContext(mock.patch.dict(sys.modules, {'gi': gi, 'gi.repository': repo}))
        loader = importlib.machinery.SourceFileLoader('aurora_play_probe', str(PLAY))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.play = importlib.util.module_from_spec(spec)
        with mock.patch('pathlib.Path.home', return_value=self.home):
            loader.exec_module(self.play)

    def test_configured_native_tool_is_found_without_a_brand_name(self):
        self.assertEqual(self.play.proton_settings_files(), [self.tool / 'user_settings.py'])
        self.assertEqual(self.play.set_mangohud(True), 0)
        self.assertTrue(self.play.mangohud_enabled())
        self.assertEqual(self.play.set_mangohud(False), 0)
        self.assertFalse((self.tool / 'user_settings.py').exists())

    def test_parent_paths_and_symlinks_deduplicate_native_tools(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.tool, target_is_directory=True)
        os.environ['STEAM_EXTRA_COMPAT_TOOLS_PATHS'] = f'{self.tool.parent}:{alias}'
        self.assertEqual(self.play.proton_settings_files(), [self.tool / 'user_settings.py'])

    def test_brand_name_without_a_native_runtime_is_not_a_tool(self):
        (self.steam / 'compatibilitytools.d/Aurora-Proton-fake').mkdir(parents=True)
        self.assertEqual(self.play.proton_settings_files(), [self.tool / 'user_settings.py'])

    def test_x86_tool_is_not_treated_as_native(self):
        (self.tool / 'files/bin/wine').write_bytes(b'\x7fELF\x02\x01' + b'\0' * 12 + b'\x3e\0')
        self.assertEqual(self.play.proton_settings_files(), [])

    def test_unmanaged_settings_are_preserved(self):
        settings = self.tool / 'user_settings.py'
        settings.write_text('user_settings = {"PROTON_LOG": "1"}\n')
        before = settings.read_bytes()
        self.assertEqual(self.play.set_mangohud(True), 1)
        self.assertEqual(self.play.set_mangohud(False), 1)
        self.assertEqual(settings.read_bytes(), before)

    @unittest.skipIf(NATIVE_TOOL is None, 'built tool supplied by the installed packaging check')
    def test_actual_packaged_native_tool_is_discovered(self):
        os.environ['STEAM_EXTRA_COMPAT_TOOLS_PATHS'] = str(NATIVE_TOOL)
        self.assertEqual(self.play.proton_settings_files(), [NATIVE_TOOL / 'user_settings.py'])

    def test_game_launch_uses_public_fhs_steam_entry(self):
        with mock.patch.object(self.play.subprocess, 'Popen') as spawn:
            self.play.Window.launch(types.SimpleNamespace(toasts=types.SimpleNamespace(add_toast=lambda _: None)),
                                  types.SimpleNamespace(appid='123', name='Example'))
        self.assertEqual(spawn.call_args.args[0], [str(self.launcher), 'steam://rungameid/123'])


if __name__ == '__main__':
    unittest.main()
