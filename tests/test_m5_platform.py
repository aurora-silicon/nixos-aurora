import configparser
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / 'm5-platform'


def ini(path):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read_string(path.read_text())
    return parser


class M5PlatformTests(unittest.TestCase):
    def test_files_are_the_recorded_fedora_copies(self):
        provenance = json.loads((FILES / 'provenance.json').read_text())
        names = {p.name for p in FILES.iterdir()} - {'provenance.json'}
        self.assertEqual(set(provenance['upstream_files_sha256']), names)
        for name, digest in provenance['upstream_files_sha256'].items():
            self.assertEqual(hashlib.sha256((FILES / name).read_bytes()).hexdigest(), digest, name)

    def test_policy_applies_on_the_j714s_only(self):
        unit = ini(FILES / 'aurora-m5-sleep-policy.service')
        self.assertEqual(unit['Unit']['ConditionFirmware'], 'device-tree-compatible(apple,j714s)')
        self.assertIn('systemd-logind.service', unit['Unit']['Before'].split())
        self.assertEqual(dict(ini(FILES / '90-aurora-m5-deep.conf')['Sleep']),
                         {'AllowSuspend': 'yes', 'SuspendState': 'mem', 'MemorySleepMode': 'deep'})
        self.assertEqual(set(ini(FILES / '90-aurora-m5-lid.conf')['Login'].values()), {'suspend'})
        hook = (FILES / '50-aurora-m5-rtc-safety').read_text().splitlines()
        first = next(line for line in hook if line and not line.startswith('#'))
        self.assertTrue(first.endswith("grep -qx 'apple,j714s' || exit 0"), first)

    def test_module_is_imported_and_links_the_hook_where_systemd_sleep_looks(self):
        module = (ROOT / 'modules/m5-platform.nix').read_text()
        self.assertIn('environment.etc."systemd/system-sleep/50-aurora-m5-rtc-safety".source', module)
        self.assertIn('systemd.services.aurora-m5-sleep-policy.wantedBy = [ "sysinit.target" ];', module)
        self.assertIn('./m5-platform.nix', (ROOT / 'modules/aurora.nix').read_text())
        overlay = (ROOT / 'overlay.nix').read_text()
        package = overlay.split('aurora-m5-platform-config = final.stdenvNoCC.mkDerivation {', 1)[1].split('\n  };\n', 1)[0]
        for replaced in ('/usr/bin/install', '/usr/share/aurora-m5-platform-config', '/usr/share/doc'):
            self.assertIn('--replace-fail ' + replaced + ' ', package)


if __name__ == '__main__':
    unittest.main()
