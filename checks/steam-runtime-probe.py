"""Executed by the real native fixture inside Steam's installed FHS launcher."""
import ctypes
import json
import os
from pathlib import Path
import sys

assert os.sysconf('SC_PAGE_SIZE') == 4096, 'descendant lost the 4 KiB process contract'
assert os.environ['AURORA_TEST_PARENT_PAGES'] == '4096'
assert os.environ['AURORA_STEAM_CONFIGURED'] == 'module-selected', 'bare package bypassed module configuration'
assert os.environ['SDL_JOYSTICK_DISABLE_UDEV'] == '1', 'Steam FHS profile was not loaded'
assert Path('/usr/bin/ldconfig').exists(), 'not running inside the packaged FHS environment'
assert ctypes.CDLL('libaurora_fixture.so').aurora_graphics_fixture() == 42, 'module graphics library was not injected'
expected = json.loads(os.environ['AURORA_TEST_EXPECTED_COMPAT'])
assert os.environ.get('STEAM_EXTRA_COMPAT_TOOLS_PATHS') == expected
report = Path(os.environ['AURORA_TEST_REPORT'])
attempt = len(report.read_text().splitlines()) if report.exists() else 0
with report.open('a') as output:
    output.write(json.dumps({'argv': sys.argv[1:], 'compat': expected, 'pages': os.sysconf('SC_PAGE_SIZE')}) + '\n')
statuses = json.loads(os.environ.get('AURORA_TEST_EXIT_CODES', '[0]'))
raise SystemExit(statuses[min(attempt, len(statuses) - 1)])
