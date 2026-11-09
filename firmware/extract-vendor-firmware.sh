#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
property=${AURORA_EFI_PROPERTY:-/sys/firmware/devicetree/base/chosen/asahi,efi-system-partition}
if [ ! -r "$property" ]; then exit 0; fi
uuid=$(tr -d '\000' < "$property")
[[ "$uuid" =~ ^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$ ]] || {
  echo 'Invalid Apple EFI partition identity' >&2; exit 1;
}
uuid=${uuid,,}
device=${AURORA_PARTUUID_ROOT:-/dev/disk/by-partuuid}/$uuid
destination=${AURORA_FIRMWARE_DESTINATION:-/run/aurora-firmware}
complete=$destination/.vendorfw-extracted
mkdir -p "$destination"
if [ ! -s "$destination/vendorfw/.vendorfw.manifest" ] || [ ! -f "$complete" ]; then
  udevadm wait --timeout=60 "$device"
  # The installed system mounts the ESP read-write, and the kernel
  # refuses a second, read-only mount of it, so a retry there reads it
  # in place.
  esp=$(findmnt --noheadings --first-only --output TARGET --source "$device" || true)
  if [ -z "$esp" ]; then
    esp=${AURORA_ESP_MOUNT:-/run/aurora-esp}
    mkdir -p "$esp"
    mount -t vfat -o ro "$device" "$esp"
    trap 'umount "$esp"' EXIT
  fi
  if [ ! -s "$esp/vendorfw/firmware.cpio" ]; then
    # Nothing to hand off; peripherals are still admitted.
    echo '<4>Aurora: the ESP has no vendor firmware; admitting peripherals without it' >&2
    exit 0
  fi
  # The archive can write its manifest before a later entry fails. Only our
  # separate marker proves extraction completed, including across an abrupt
  # interruption; a retry replaces whatever the previous attempt left behind.
  rm -f "$complete"
  (cd "$destination"; cpio --quiet --extract --unconditional --no-absolute-filenames < "$esp/vendorfw/firmware.cpio")
  touch "$complete"
fi
