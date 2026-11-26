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
# A signed boot binds the archive: the UKI's command line, which its
# signature covers, carries aurora.vendorfw=sha256:<digest>, or
# aurora.vendorfw=none when no archive was trusted (modules/secure-boot.nix).
# The ESP is outside that signature, so an archive that does not match is
# never used. A boot without the parameter is not signed (GRUB, image boots)
# and takes the archive as it is. A parameter with an empty value is a
# malformed one, not a missing one.
bound=
expected=
words=()
read -r -a words < "${AURORA_KERNEL_CMDLINE:-/proc/cmdline}" || true
for word in "${words[@]}"; do
  case $word in aurora.vendorfw=*) bound=1; expected=${word#aurora.vendorfw=} ;; esac
done
mkdir -p "$destination"
if [ ! -s "$destination/vendorfw/.vendorfw.manifest" ] || [ ! -f "$complete" ]; then
  udevadm wait --timeout=60 "$device"
  # The installed system mounts the ESP read-write, and the kernel
  # refuses a second, read-only mount of it, so a retry there reads it
  # in place.
  esp=$(findmnt --noheadings --first-only --output TARGET --source "$device" || true)
  mounted=
  copy=$destination/.vendorfw.cpio
  trap 'rm -f "$copy"; if [ -n "$mounted" ]; then umount "$esp"; fi' EXIT
  if [ -z "$esp" ]; then
    esp=${AURORA_ESP_MOUNT:-/run/aurora-esp}
    mkdir -p "$esp"
    mount -t vfat -o ro "$device" "$esp"
    mounted=1
  fi
  archive=$esp/vendorfw/firmware.cpio
  if [ ! -s "$archive" ]; then
    # Nothing to hand off; peripherals are still admitted.
    echo '<4>Aurora: the ESP has no vendor firmware; admitting peripherals without it' >&2
    exit 0
  fi
  if [ -n "$bound" ]; then
    if [[ ! "$expected" =~ ^sha256:[0-9a-f]{64}$ ]]; then
      echo "<3>Aurora: this signed boot trusts no vendor firmware archive (aurora.vendorfw=$expected); not using the one on the ESP" >&2
      exit 1
    fi
    # Check, then extract, the same bytes: a private copy, not the ESP file
    # read a second time.
    rm -f "$copy"
    cp -- "$archive" "$copy"
    actual=$(sha256sum < "$copy")
    if [ "sha256:${actual%% *}" != "$expected" ]; then
      echo '<3>Aurora: the vendor firmware on the ESP does not match the digest in this signed boot; not using it' >&2
      exit 1
    fi
    archive=$copy
  fi
  # The archive can write its manifest before a later entry fails. Only our
  # separate marker proves extraction completed, including across an abrupt
  # interruption; a retry replaces whatever the previous attempt left behind.
  rm -f "$complete"
  (cd "$destination"; cpio --quiet --extract --unconditional --no-absolute-filenames < "$archive")
  touch "$complete"
fi
