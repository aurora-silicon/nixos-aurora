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
# The kernel searches firmware_class.path first, then /lib/firmware. Point it
# at the per-device tree before admission loads any driver: in the initrd for
# the keyboard, and again on the real root, where NixOS activation has
# replaced it with the Nix store firmware tree. No kernel parameter is needed.
parameter=${AURORA_FIRMWARE_PARAMETER:-/sys/module/firmware_class/parameters/path}
if [[ "${1:-initrd}" == runtime ]]; then
  # Keep the store tree reachable through the kernel's /lib/firmware fallback.
  fallback=${AURORA_FIRMWARE_FALLBACK:-/lib/firmware}
  system_firmware=${AURORA_SYSTEM_FIRMWARE:-/run/current-system/firmware}
  if [[ ! -e "$fallback" && ! -L "$fallback" ]]; then
    ln -s "$system_firmware" "$fallback"
  fi
  [[ -d "$fallback" ]] || { echo 'System firmware fallback is unavailable' >&2; exit 1; }
  printf '%s' "$destination/vendorfw" > "$parameter"
  export AURORA_ADMIT_BLUETOOTH=1
  if [[ "$status" = 0 ]]; then
    export AURORA_RUNTIME_FIRMWARE_READY=1
  fi
elif [[ -e "$parameter" ]]; then
  printf '%s' "$destination/vendorfw" > "$parameter"
fi
aurora-peripheral-admission
exit "$status"
