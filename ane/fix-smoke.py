from pathlib import Path
p = Path("packaging/omarchy-ane-smoke")
s = p.read_text()
assert 'HERE.parent / "fixtures"' in s
s = s.replace('HERE.parent / "fixtures"', 'HERE.parent / "share/omarchy-ane/fixtures"')
s = s.replace("omarchy-ane-dkms", "omarchy-ane-tools")
p.write_text(s)
