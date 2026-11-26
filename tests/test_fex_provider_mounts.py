"""The FEX guest graphics provider and its bind are read-only, nosuid and nodev.

modules/fex-mesa.nix mounts the provider; modules/aurora-fex-rootfs.sh binds
it for FEX. The fex-overlay-upgrade check runs both in a VM; this runs the
script alone. alarm-aurora's and fedora-aurora's tests of the same script use
the same mount doubles: a stack of "path device busy flags" lines, newest last, so the
overlay and its binds are modelled without mounting anything. A bind takes its
source's flags and adds its own options, as util-linux applies them to the new
bind; a bind remount sets the flags of the newest mount at a path.
"""
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'modules/fex-mesa.nix'
SCRIPT = ROOT / 'modules/aurora-fex-rootfs.sh'
PROVIDER = '/var/lib/aurora/fex/mesa-rootfs'

MOUNT_DOUBLES = {
    'mountpoint': '''#!/bin/bash
[[ $1 == -q ]] && shift
grep -q "^$1 " "$TEST_ROOT/mounts"
''',
    'umount': '''#!/bin/bash
printf 'umount %s\\n' "$*" >> "$TEST_ROOT/log"
line=$(grep -n "^$1 " "$TEST_ROOT/mounts" | tail -n1) || exit 32
[[ $(cut -d' ' -f3 <<<"${line#*:}") == 0 ]] || exit 32
sed -i "${line%%:*}d" "$TEST_ROOT/mounts"
''',
    'mount': '''#!/bin/bash
printf 'mount %s\\n' "$*" >> "$TEST_ROOT/log"
if [[ $1 == -o && $2 == remount,bind,* && $# == 3 ]]; then
  [[ ${REMOUNT_FAILS:-no} == no ]] || exit 1
  line=$(grep -n "^$3 " "$TEST_ROOT/mounts" | tail -n1) || exit 32
  read -r path dev busy _ <<<"${line#*:}"
  sed -i "${line%%:*}s|.*|$path $dev $busy ${2#remount,bind,}|" "$TEST_ROOT/mounts"
  exit 0
fi
[[ $1 == --bind && $2 == -o && $# == 5 ]] || exit 2
read -r _ dev _ flags <<<"$(grep "^$4 " "$TEST_ROOT/mounts" | tail -n1)"
flags=$(printf '%s\\n' ${flags//,/ } ${3//,/ } | sort -u | paste -sd,)
echo "$5 ${dev:?} 0 $flags" >> "$TEST_ROOT/mounts"
''',
    'stat': '''#!/bin/bash
[[ $1 == -c && $2 == %d ]] || exit 2
dev=$(grep "^$3 " "$TEST_ROOT/mounts" | tail -n1 | cut -d' ' -f2)
echo "${dev:-root}"
''',
}

# A Fedora-style guest: the x86-64 loader and the layer's x86-64 driver side by side.
X86_64 = b'\x7fELF\x02\x01\x01' + bytes(9) + b'\x03\x00\x3e\x00'
TREE = {'.aurora-mesa-commit': b'', 'usr/lib64/ld-linux-x86-64.so.2': X86_64,
        'usr/lib64/libvulkan_asahi.so': X86_64}


class OverlayUnitTests(unittest.TestCase):
    def test_overlay_is_read_only_nosuid_nodev(self):
        start = re.search(r'ExecStart = utils\.escapeSystemdExecArgs \[(.*?)\];', MODULE.read_text(), re.S)
        self.assertIsNotNone(start)
        args = re.findall(r'"([^"]*)"', start.group(1))
        self.assertIn('overlay', args)
        options = args[args.index('-o') + 1].split(',')
        self.assertTrue({'ro', 'nosuid', 'nodev'} <= set(options), options)


class RootfsBindTests(unittest.TestCase):
    def run_select(self, mounts, remount_fails=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        provider, run = root / 'provider', root / 'run/fex-emu'
        for name, data in TREE.items():
            (provider / name).parent.mkdir(parents=True, exist_ok=True)
            (provider / name).write_bytes(data)
        names = {'provider': str(provider), 'rootfs': str(run / 'rootfs')}
        (root / 'mounts').write_text(''.join(f'{names[p]} {d} {b} {f}\n' for p, d, b, f in mounts))
        (root / 'log').touch()
        bin_dir = root / 'bin'
        bin_dir.mkdir()
        for name, text in MOUNT_DOUBLES.items():
            (bin_dir / name).write_text(text)
            (bin_dir / name).chmod(0o755)
        script = SCRIPT.read_text()
        self.assertIn(f'provider={PROVIDER}\n', script)
        self.assertIn('dir=/run/fex-emu\n', script)
        script = script.replace(f'provider={PROVIDER}\n', f'provider={provider}\n')
        script = script.replace('dir=/run/fex-emu\n', f'dir={run}\n')
        env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}', TEST_ROOT=str(root),
                   REMOUNT_FAILS='yes' if remount_fails else 'no')
        result = subprocess.run(['sh', '-c', script], env=env, stderr=subprocess.PIPE, text=True)
        reverse = {v: k for k, v in names.items()}
        stack = [line.split() for line in (root / 'mounts').read_text().splitlines()]
        flags = {reverse[p]: set(f.split(',')) for p, _, _, f in stack}
        config = run / 'Config.json'
        selected = json.loads(config.read_text()) if config.exists() else None
        return result, [(reverse[p], d, b) for p, d, b, _ in stack], flags, selected, str(run / 'rootfs')

    def test_new_bind_is_read_only_nosuid_nodev(self):
        # Also over a provider mounted read-only only, as before.
        for provider_flags in ('ro', 'ro,nosuid,nodev'):
            with self.subTest(provider=provider_flags):
                result, stack, flags, selected, rootfs = self.run_select([('provider', 'ovl1', 0, provider_flags)])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(stack, [('provider', 'ovl1', '0'), ('rootfs', 'ovl1', '0')])
                self.assertEqual(flags['rootfs'], {'ro', 'nosuid', 'nodev'})
                self.assertEqual(selected, {'Config': {'RootFS': rootfs}})

    def test_kept_bind_gets_nosuid_nodev(self):
        # A bind made read-only only, before this, that a program still uses.
        result, stack, flags, selected, rootfs = self.run_select(
            [('provider', 'ovl1', 0, 'ro'), ('rootfs', 'ovl1', 1, 'ro')])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(stack, [('provider', 'ovl1', '0'), ('rootfs', 'ovl1', '1')])
        self.assertEqual(flags['rootfs'], {'ro', 'nosuid', 'nodev'})
        self.assertEqual(selected, {'Config': {'RootFS': rootfs}})

    def test_failed_remount_leaves_no_runtime_rootfs(self):
        result, _, _, selected, _ = self.run_select([('provider', 'ovl1', 0, 'ro')], remount_fails=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(selected)
        self.assertIn('nosuid and nodev', result.stderr)


if __name__ == '__main__':
    unittest.main()
