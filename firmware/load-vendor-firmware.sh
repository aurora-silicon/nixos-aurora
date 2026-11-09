#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
destination=${AURORA_FIRMWARE_DESTINATION:-/run/aurora-firmware}
# Extraction runs as its own process so that its errors stop it, while
# the keyboard and the other peripherals are still admitted below.
status=0
aurora-extract-vendor-firmware || status=$?
if [[ "$status" != 0 && "${1:-initrd}" != runtime ]]; then
  # The installed system's aurora-vendor-firmware.service retries the
  # handoff and reports its result.
  echo '<4>Aurora: vendor firmware handoff failed; the installed system will retry it' >&2
  status=0
fi
export AURORA_FIRMWARE_ROOT="$destination/vendorfw"
export AURORA_ADMIT_BLUETOOTH=0
export AURORA_RUNTIME_FIRMWARE_READY=0
if [[ "${1:-initrd}" == runtime ]]; then
  # Activation replaces the initrd's firmware_class.path with the Nix
  # store firmware tree. Restore the per-device path while retaining the
  # store tree through the kernel's standard /lib/firmware fallback.
  fallback=${AURORA_FIRMWARE_FALLBACK:-/lib/firmware}
  system_firmware=${AURORA_SYSTEM_FIRMWARE:-/run/current-system/firmware}
  parameter=${AURORA_FIRMWARE_PARAMETER:-/sys/module/firmware_class/parameters/path}
  if [[ ! -e "$fallback" && ! -L "$fallback" ]]; then
    ln -s "$system_firmware" "$fallback"
  fi
  [[ -d "$fallback" ]] || { echo 'System firmware fallback is unavailable' >&2; exit 1; }
  printf '%s' "$destination/vendorfw" > "$parameter"
  export AURORA_ADMIT_BLUETOOTH=1
  if [[ "$status" = 0 ]]; then
    export AURORA_RUNTIME_FIRMWARE_READY=1
  fi
fi
aurora-peripheral-admission
exit "$status"
