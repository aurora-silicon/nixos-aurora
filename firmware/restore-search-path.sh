#!/bin/sh
# Restore only the per-device search path after NixOS udev activation. A
# switch must not repeat firmware extraction or probe any running device.
set -eu
parameter=${1:-/sys/module/firmware_class/parameters/path}
vendor=${2:-/run/aurora-firmware/vendorfw}

# During image assembly and before the boot handoff there is no per-device
# tree. Leave NixOS's store firmware path until the runtime loader is ready.
if [ -e "$parameter" ] && [ -d "$vendor" ]; then
  printf '%s' "$vendor" > "$parameter"
fi
