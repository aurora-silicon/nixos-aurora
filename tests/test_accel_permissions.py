"""The Neural Engine node's permissions on every install, not only with the ANE tools."""
import fnmatch
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / 'modules'

# systemd's own rule for the subsystem (50-udev-default.rules), and the file
# that runs the uaccess builtin for nodes tagged uaccess.
SYSTEMD_RULES = {
    '50-udev-default.rules': 'SUBSYSTEM=="accel", GROUP="render", MODE="0666"\n',
}
SEAT_LATE = '73-seat-late.rules'
TOKEN = re.compile(r'([A-Z_]+(?:\{[^}]*\})?)\s*(==|!=|\+=|-=|:=|=)\s*"([^"]*)"')


def rules(text):
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            yield TOKEN.findall(line)


def matches(pattern, value):
    return any(fnmatch.fnmatchcase(value, alt) for alt in pattern.split('|'))


def apply(files, device):
    """Group, mode and tags that udev leaves on device after the files, in name order."""
    state = {'GROUP': 'root', 'MODE': '0600', 'TAG': set()}
    for name in sorted(files):
        for tokens in rules(files[name]):
            ok = True
            for key, op, value in tokens:
                if op == '==':
                    ok = ok and matches(value, device.get(key, ''))
                elif op == '!=':
                    ok = ok and not matches(value, device.get(key, ''))
            if not ok:
                continue
            for key, op, value in tokens:
                if key == 'TAG' and op == '+=':
                    state['TAG'].add(value)
                elif key in ('GROUP', 'MODE') and op in ('=', ':='):
                    state[key] = value
    return state


def rule_files(directory):
    return {p.name: p.read_text() for p in directory.iterdir() if p.name.endswith('.rules')}


class AccelPermissionTests(unittest.TestCase):
    NODE = {'SUBSYSTEM': 'accel', 'KERNEL': 'accel0'}

    def test_platform_rule_restricts_the_node_to_accel_and_the_session_user(self):
        files = dict(SYSTEMD_RULES)
        files.update(rule_files(MODULES))
        state = apply(files, self.NODE)
        self.assertEqual((state['GROUP'], state['MODE']), ('accel', '0660'))
        self.assertIn('uaccess', state['TAG'])
        # The tag must be set before the seat rules act on it.
        accel = [n for n, t in files.items() if 'SUBSYSTEM=="accel"' in t and n not in SYSTEMD_RULES]
        self.assertEqual(accel, ['70-aurora-accel.rules'])
        self.assertLess(accel[0], '71-seat.rules')
        self.assertLess(accel[0], SEAT_LATE)
        # Other accel nodes get the same policy; nothing else does.
        self.assertEqual(apply(files, {'SUBSYSTEM': 'accel', 'KERNEL': 'accel3'})['MODE'], '0660')
        self.assertEqual(apply(files, {'SUBSYSTEM': 'drm', 'KERNEL': 'renderD128'})['GROUP'], 'root')

    def test_platform_module_installs_the_rule_and_the_group_on_every_system(self):
        platform = (MODULES / 'platform.nix').read_text()
        rule = platform.split('name = "aurora-accel-rules";', 1)[1].split('};', 1)[0]
        self.assertIn('destination = "/lib/udev/rules.d/70-aurora-accel.rules";', rule)
        self.assertIn('text = builtins.readFile ./70-aurora-accel.rules;', rule)
        self.assertIn('\n    accelRules\n  ];', platform)
        self.assertRegex(platform, r'(?m)^  users\.groups\.accel = \{ \};$')
        # platform.nix has no enable option: every Aurora system imports it.
        self.assertNotIn('mkIf', platform)
        self.assertIn('./platform.nix', (MODULES / 'aurora.nix').read_text())
        self.assertIn('"aurora-accel-rules"', (ROOT / 'checks' / 'fedora-parity.nix').read_text())

    def test_a_switch_reapplies_the_policy_to_existing_nodes(self):
        platform = (MODULES / 'platform.nix').read_text()
        unit = platform.split('systemd.services.aurora-accel-permissions = {', 1)[1].split('\n  };\n', 1)[0]
        # An add event: a change event does not reapply GROUP and MODE.
        self.assertIn('trigger --action=add --subsystem-match=accel', unit)
        self.assertNotIn('--action=change', unit)
        # Restarted when the rule changes, after udevd, and only with a running udevd;
        # a failure does not fail the switch.
        self.assertIn('restartTriggers = [ accelRules ];', unit)
        self.assertIn('"systemd-udevd.service"', unit)
        self.assertIn('ConditionPathExists = "/run/udev/control";', unit)
        self.assertEqual(unit.count('"-${udevadm} '), 2)
        self.assertIn('RemainAfterExit = true;', unit)

    def test_the_ane_tools_carry_no_device_policy(self):
        self.assertEqual(rule_files(ROOT / 'ane'), {})
        self.assertFalse(list((ROOT / 'ane').glob('*.sysusers')))
        package = (ROOT / 'omarchy-ane-tools.nix').read_text()
        self.assertNotIn('rules.d', package)
        self.assertNotIn('sysusers.d', package)
        module = (MODULES / 'ane.nix').read_text()
        self.assertNotIn('users.groups', module)
        self.assertNotIn('services.udev', module)

    def test_no_other_file_sets_accel_permissions(self):
        owners = sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob('*.rules')
                        if '.git' not in p.parts and 'SUBSYSTEM=="accel"' in p.read_text())
        self.assertEqual(owners, ['modules/70-aurora-accel.rules'])
        for nix in ROOT.rglob('*.nix'):
            if '.git' not in nix.parts and nix.name != 'fedora-parity.nix':
                self.assertNotIn('SUBSYSTEM=="accel"', nix.read_text(), nix)


if __name__ == '__main__':
    unittest.main()
