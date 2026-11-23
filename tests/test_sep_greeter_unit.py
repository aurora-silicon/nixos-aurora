"""The login screen fingerprint service only puts a GResource overlay in
place for the login screen's shell. It is ordered before the display manager
and must not order it after the Secure Enclave: aurora-sep-ready takes
seconds, and the login screen would wait for it."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'modules' / 'sep.nix'
SEP = ROOT / 'sep'
# Units that finish only once the enclave is up.
ENCLAVE = {'aurora-sep.service', 'aurora-sep-ready.service', 'fprintd.service',
           'aurora-touchid-boot.service', 'aurora-touchid-setup.service'}


def service():
    """The attribute set of systemd.services.aurora-sep-greeter-fingerprint,
    without comments."""
    text = MODULE.read_text()
    start = text.index('systemd.services.aurora-sep-greeter-fingerprint = {')
    depth, end = 0, None
    for index in range(text.index('{', start), len(text)):
        if text[index] == '{':
            depth += 1
        elif text[index] == '}':
            depth -= 1
            if depth == 0:
                end = index
                break
    return re.sub(r'#.*', '', text[start:end])


def names(key):
    found = re.search(rf'^\s*{key}\s*=\s*\[([^\]]*)\];', service(), re.M)
    return set(re.findall(r'"([^"]+)"', found.group(1))) if found else set()


class GreeterUnit(unittest.TestCase):
    def test_does_not_wait_for_the_enclave(self):
        for key in ('after', 'wants', 'requires', 'bindsTo'):
            with self.subTest(key=key):
                self.assertFalse(names(key) & ENCLAVE)

    def test_runs_before_the_login_screen(self):
        self.assertIn('display-manager.service', names('before'))
        self.assertEqual(names('wantedBy'), {'display-manager.service'})

    def test_does_not_pull_in_a_login_screen_restart(self):
        # The linux tree ships aurora-sep-greeter-refresh.service, which
        # restarts the login screen when Touch ID comes up.
        self.assertNotIn('aurora-sep-greeter-refresh', re.sub(r'#.*', '', MODULE.read_text()))
        self.assertFalse((SEP / 'aurora-sep-greeter-refresh.service').exists())

    def test_provenance_names_the_adaptation(self):
        provenance = json.loads((SEP / 'provenance.json').read_text())
        self.assertIn('aurora-sep-greeter-fingerprint.service', provenance['file_commits'])
        self.assertIn('aurora-sep-greeter-refresh.service', provenance['adaptations'])


if __name__ == '__main__':
    unittest.main()
