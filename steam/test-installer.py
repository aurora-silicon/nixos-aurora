#!/usr/bin/env python3
"""The NixOS client installer keeps aliases without replacing system launchers."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from unittest import mock

spec = importlib.util.spec_from_file_location('installer', sys.argv[1])
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
with tempfile.TemporaryDirectory() as temporary:
    base = Path(temporary)
    home, client, prefix = base / 'home', base / 'client', base / 'prefix'
    home.mkdir()
    (client / 'linuxarm64').mkdir(parents=True)
    with mock.patch.dict(os.environ, {'AURORA_SYSTEM_LAUNCHERS': '1'}):
        installer.install_launcher(client, prefix, home)
    assert (home / '.steam/root').resolve() == client
    assert (home / '.steam/steam').resolve() == client
    assert (home / '.steam/sdkarm64').resolve() == client / 'linuxarm64'
    assert not prefix.exists(), 'the NixOS installer must not create user launchers/desktops'
