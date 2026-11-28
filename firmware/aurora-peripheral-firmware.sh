#!/bin/sh
# SPDX-License-Identifier: MIT
# Never reset a running device. Repeated modprobe of a loaded module is inert.
set -eu
firmware_root=${AURORA_FIRMWARE_ROOT:-/lib/firmware}
dt=${AURORA_DT_ROOT:-/sys/firmware/devicetree/base}
modprobe_command=${AURORA_MODPROBE:-modprobe}
pci_root=${AURORA_PCI_ROOT:-/sys/bus/pci/devices}

has_firmware() {
  [ -s "$firmware_root/vendor/$1" ] || [ -s "$firmware_root/$1" ]
}

# The Touch Bar digitizer of the J293 and J493 reads apple/dfrmtfw-<board>.bin.
has_touch_bar_firmware() {
  for file in "$firmware_root"/apple/dfrmtfw-*.bin "$firmware_root"/vendor/apple/dfrmtfw-*.bin; do
    [ -s "$file" ] && return 0
  done
  return 1
}

# Print every device-tree node whose compatible list has the entry $1.
dt_nodes() {
  find "$dt" -name compatible -type f -exec grep -lzxF -e "$1" {} + |
    while read -r path; do echo "${path%/compatible}"; done
}

# An AOP ambient light sensor whose node names a calibration file reads it
# while aop probes, and aop does not probe again. Hold aop back until the
# file is in place.
aop_ready=true
for node in $(dt_nodes apple,aop-als); do
  [ -r "$node/firmware-name" ] || continue
  calibration=$(tr -d '\000' < "$node/firmware-name")
  if ! has_firmware "$calibration"; then
    echo "Aurora: ALS calibration $calibration missing; AOP probe deferred" >&2
    aop_ready=false
  fi
done

# A MediaTek MT7932 radio (Wi-Fi and Bluetooth, the PCI function behind the
# wifi0 alias) is held back from autoload: its drivers read these files
# while probing and do not probe again.
radio_ready=false
wifi=
if [ -r "$dt/aliases/wifi0" ]; then
  wifi=$(tr -d '\000' < "$dt/aliases/wifi0")
fi
if [ -n "$wifi" ] && tr '\000' '\n' < "$dt$wifi/compatible" | grep -qxF pci14c3,7932; then
  radio_ready=true
  for name in \
    mediatek/mt7932/IZUBA_WIFI_MT7932_patch_mcu_1_2_hdr.bin \
    mediatek/mt7932/IZUBA_W7932_2.bin \
    mediatek/mt7932/ppr.bin mediatek/mt7932/oca2.bin \
    mediatek/mt7932/wcal.bin mediatek/mt7932/config-original.bin \
    mediatek/MT7932B0_OS_TypeB_0.1.44.0_241001003711.bin \
    mediatek/MT7932B1_OS_TypeB_0.1.133.0_260128190103.bin \
    mediatek/MT7932_PTB_IzubaA_0.1.0.0_20251021141303.ptx \
    mediatek/j700-mt7932-btcal.bin mediatek/j700-mt7932-bdaddr.bin \
    mediatek/mt7932/policy/world-XZ.bin; do
    if ! has_firmware "$name"; then
      echo "Aurora: required firmware is missing: $name; peripheral probe deferred" >&2
      radio_ready=false
    fi
  done
fi

# A built-in trackpad on the keyboard's DockChannel reads the file that its
# multi-touch node names in firmware-name while it probes. Without the
# property the driver sends no firmware, so there is nothing to check.
for node in $(dt_nodes apple,dockchannel-hid); do
  [ -r "$node/multi-touch/firmware-name" ] || continue
  trackpad=$(tr -d '\000' < "$node/multi-touch/firmware-name")
  if ! has_firmware "$trackpad"; then
    echo "Aurora: trackpad firmware $trackpad missing; keyboard probe continues" >&2
  fi
done
# The Neo and M2 and later MacBooks share this keyboard and trackpad driver.
# Its autoload waits for firmware, so load it on every Mac; a Mac without
# the device only loads the module.
"$modprobe_command" dockchannel-hid

if "$aop_ready"; then
  "$modprobe_command" aop
fi
if "$radio_ready"; then
  "$modprobe_command" mt7932-fullmac
  if [ "${AURORA_ADMIT_BLUETOOTH:-0}" = 1 ]; then
    "$modprobe_command" mt7932_bt_pcie
  fi
fi

if [ "${AURORA_RUNTIME_FIRMWARE_READY:-0}" = 1 ]; then
  # Resolve aliases with the running kernel instead of maintaining PCI IDs.
  # These drivers were held back from udev until extraction and the real-root
  # firmware search path were ready. Do not probe a partial firmware archive.
  if [ -d "$firmware_root/brcm" ] || [ -d "$firmware_root/vendor/brcm" ]; then
    for device in "$pci_root"/*; do
      [ -r "$device/modalias" ] || continue
      read -r alias < "$device/modalias" || continue
      if modules=$("$modprobe_command" --resolve-alias "$alias" 2>/dev/null); then
        for module in $modules; do
          case "$module" in
            brcmfmac) "$modprobe_command" "$module" ;;
            hci_bcm4377)
              if [ "${AURORA_ADMIT_BLUETOOTH:-0}" = 1 ]; then
                "$modprobe_command" "$module"
              fi
              ;;
          esac
        done
      fi
    done
  fi

  # The Touch Bar digitizer uploads its firmware while probing and does not
  # retry a failed probe. Its SPI device can appear after this pass, so load
  # the driver by name; it binds whenever the device registers.
  if has_touch_bar_firmware; then
    "$modprobe_command" apple_z2
  fi

  # The ALS child reads calibration while probing, so it must follow the
  # runtime path restoration too. Calibration remains optional for sensors
  # that work without it; the driver diagnoses a missing required blob.
  "$modprobe_command" aop_als
fi
