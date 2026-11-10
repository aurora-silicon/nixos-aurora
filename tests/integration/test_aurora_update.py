"""Exercise updater flake resolution, selected locking and evaluation with real Nix."""
from contextlib import redirect_stderr
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('integration_aurora_update', ROOT / 'scripts/aurora-update.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class RealNixUpdateTests(unittest.TestCase):
    def test_local_consumer_updates_only_selected_input_without_remembering_unactivated_system(self):
        if any(shutil.which(tool) is None for tool in ('nix', 'git')):
            self.fail('Updater integration requires Git and Nix with nix-command and flakes support')
        root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='aurora updater integration ')))
        self.enterContext(patch.dict(os.environ, {
            'NIX_CONFIG': '\n'.join([
                'experimental-features = nix-command flakes',
                'store = local?root=' + str(root / 'store'),
                'sandbox = false', 'substituters =', 'build-users-group =',
                'warn-dirty = false',
            ]),
            'XDG_CACHE_HOME': str(root / 'cache'),
            'XDG_CONFIG_HOME': str(root / 'config'),
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
        }))

        def nix(*args):
            result = subprocess.run(['nix', *args], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.strip()

        selected, retained, consumer = (root / name for name in ('selected input', 'retained input', 'consumer flake'))
        reference = str(consumer)
        for directory in (selected, retained, consumer):
            directory.mkdir()

        def input_flake(directory, version):
            (directory / 'flake.nix').write_text('{ outputs = { self }: { value = ' + json.dumps(version) + '; }; }\n')

        input_flake(selected, 'selected-old')
        input_flake(retained, 'retained-old')
        selector = 'host with spaces.and-dots'
        system = nix('eval', '--impure', '--raw', '--expr', 'builtins.currentSystem')
        (consumer / 'flake.nix').write_text('''{
  inputs.selected.url = ''' + json.dumps(selected.as_uri().replace('file://', 'path:', 1)) + ''';
  inputs.retained.url = ''' + json.dumps(retained.as_uri().replace('file://', 'path:', 1)) + ''';
  outputs = { self, selected, retained }: {
    nixosConfigurations.''' + json.dumps(selector) + '''.config.system.build.toplevel = builtins.derivation {
      name = "aurora-update-${selected.value}-${retained.value}";
      system = ''' + json.dumps(system) + ''';
      builder = "/bin/sh";
      args = [ "-c" "printf updater-fixture > $out" ];
    };
  };
}
''')
        def git(*args):
            subprocess.run(['git', '-C', str(consumer), '-c', 'user.name=Updater fixture',
                            '-c', 'user.email=updater@example.invalid', '-c', 'commit.gpgsign=false', *args],
                           check=True, capture_output=True)

        git('init', '-q', '-b', 'main')
        git('add', 'flake.nix')
        nix('flake', 'lock', reference)
        git('add', 'flake.lock')
        git('commit', '-qm', 'local consumer fixture')
        before = json.loads((consumer / 'flake.lock').read_text())
        configuration = 'configurations: (builtins.getAttr ' + json.dumps(selector) + ' configurations).config.system.build.toplevel.name'
        self.assertEqual(nix('eval', '--raw', reference + '#nixosConfigurations', '--apply', configuration),
                         'aurora-update-selected-old-retained-old')
        input_flake(selected, 'selected-new')
        input_flake(retained, 'retained-new')
        active = root / 'old-system'
        active.mkdir()
        current = root / 'current-system'
        current.symlink_to(active)
        state = root / 'state'
        log = root / 'rebuild-argv.json'
        rebuild = root / 'record rebuild'
        rebuild.write_text(f'#!{sys.executable}\nimport json, pathlib, sys\n'
                           f'pathlib.Path({str(log)!r}).write_text(json.dumps(sys.argv[1:]))\n')
        rebuild.chmod(0o755)
        error = io.StringIO()
        with patch.object(updater.os, 'geteuid', return_value=0), redirect_stderr(error):
            status = updater.main(['--flake', reference + '#' + selector, '--input', 'selected'],
                                  state_dir=state, current_system=current, rebuild=str(rebuild), owner_uid=os.getuid())
        self.assertEqual(status, 0, error.getvalue())
        after = json.loads((consumer / 'flake.lock').read_text())
        selected_node = before['nodes']['root']['inputs']['selected']
        retained_node = before['nodes']['root']['inputs']['retained']
        self.assertNotEqual(before['nodes'][selected_node]['locked'], after['nodes'][selected_node]['locked'])
        self.assertEqual(before['nodes'][retained_node], after['nodes'][retained_node])
        metadata = json.loads(nix('flake', 'metadata', '--json', '--no-write-lock-file', reference))
        self.assertEqual(json.loads(log.read_text()), ['switch', '--flake', metadata['resolvedUrl'] + '#' + selector])
        self.assertEqual(nix('eval', '--raw', reference + '#nixosConfigurations', '--apply', configuration),
                         'aurora-update-selected-new-retained-old')
        self.assertEqual(current.resolve(), active)
        self.assertFalse(state.exists())
        self.assertIn('source not remembered', error.getvalue())


if __name__ == '__main__':
    unittest.main()
