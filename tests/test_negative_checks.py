"""CI scripts write negative checks with scripts/testlib.sh, not "! cmd".

Bash ignores the status of "! cmd" under set -e, so such a line never fails
a test, and "refute grep" passes when grep itself fails (a missing file).
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
# A statement that is only a negated command; "! a || fail" still decides.
BARE = re.compile(r'^\s*!\s+(?!.*\|\|)')
WEAK = {
    re.compile(r'\brefute\s+grep\b'): 'use nomatch',
}


def shell_sources():
    for path in sorted((ROOT / 'scripts').rglob('*')):
        if path.is_file() and path.suffix != '.py':
            yield path, path.read_text(errors='replace')
    for path in sorted((ROOT / '.github/workflows').glob('*.yml')):
        yield path, path.read_text()


def findings(text):
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith('#'):
            continue
        if BARE.match(line):
            found.append((number, 'bare "! cmd" never fails under set -e', line.strip()))
        for pattern, advice in WEAK.items():
            if pattern.search(line):
                found.append((number, advice, line.strip()))
    return found


class NegativeCheckTests(unittest.TestCase):
    def test_scripts_use_the_shared_checks(self):
        problems = [f'{path.relative_to(ROOT)}:{number}: {why}: {line}'
                    for path, text in shell_sources() for number, why, line in findings(text)]
        self.assertEqual(problems, [])

    def test_the_lint_catches_each_weak_form(self):
        for line in ['! rpm -q mesa-libGL-devel', "  ! grep -F 'not found' ldd.txt",
                     '! systemctl is-active x && echo', "refute grep -Fx a b"]:
            self.assertTrue(findings(line), line)
        for line in ["nomatch -F 'not found' ldd.txt",
                     '! asked "$out" || fail "asked"', '[[ ! -e $file ]]', 'if ! grep -q a b; then',
                     '# ! comment']:
            self.assertFalse(findings(line), line)


if __name__ == '__main__':
    unittest.main()
