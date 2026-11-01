"""Keep downloaded bytes local; hardware.firmware publishes only owner inputs."""
from pathlib import Path
p = Path('packaging/omarchy-ane-firmware-fetch')
s = p.read_text()
# Fetch and diagnostics use the staging tree. Checks must inspect the activated
# firmware tree instead: a staged file alone cannot be loaded by the kernel.
s = s.replace('usr/lib/firmware', 'var/lib/aurora/ane-firmware')
# Diagnostics in vendor_copy/loader_copy describe the active fallback.
s = s.replace("root / 'var/lib/aurora/ane-firmware' / name",
              "root / 'run/current-system/firmware' / name")
s = s.replace('VENDOR = "var/lib/aurora/ane-firmware/vendor"',
              'VENDOR = "run/aurora-firmware/vendorfw"')
a = s.index('def check(root):')
s = s[:a] + s[a:].replace('dest = root / "var/lib/aurora/ane-firmware" / name',
                         'dest = root / "run/current-system/firmware" / name')
s = s.replace('is missing. Run: sudo omarchy-ane-firmware-fetch',
              'is missing. Fetch firmware, configure aurora.ane.firmwarePackage, then rebuild NixOS')
s = s.replace('then reboot.', 'then configure aurora.ane.firmwarePackage and rebuild NixOS.')
p.write_text(s)
