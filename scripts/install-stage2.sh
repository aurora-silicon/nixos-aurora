#!/usr/bin/env bash
# Install the Stage 2 on this Mac's ESP the way update-m1n1 does on ALARM and
# Fedora: only when it changes, and as a trial when Stage 1 can run one.
# Every Mac uses the combined m1n1/boot.bin until aura has no monitor. Then a
# Mac that boots a Mach-O Stage 1 uses m1n1/boot-ctxr.bin with only its board's
# device trees, and its m1n1/boot.bin is never touched. Stage 1 is never
# written. This script refuses (leaving the ESP as it was) when the input does
# not match its recorded digest or the ESP is not the mounted FAT partition this
# Mac booted from. A Mach-O Mac whose board has no file in this build only gets
# a warning.
#
# The write itself is aurora-stage2 install (stage2/nixos_stage2.py, the
# fedora-aurora updater's trial logic): with aura Stage 1 1.0.0b4 or later it
# arms <name>.next as a one-shot aura-try trial that aurora-stage2-commit makes
# live after a good boot; otherwise it replaces the file and keeps the previous
# one as .old. Either way it first refuses device trees whose DT ABI generation
# a configuration GRUB lists cannot boot.
#
#   install-stage2.sh STAGE2_DIR ESP_MOUNTPOINT [TOPLEVEL]
#
# STAGE2_DIR holds boot.bin and its .sha256 from the checked build, aura.bin and
# dtb-abi. With aura's monitor gone it also holds monitor-free and
# ctxr/boot-ctxr-<board>.bin with their .sha256. TOPLEVEL is the configuration
# being installed.
set -euo pipefail

source_dir=${1:-}
esp=${2:-}
toplevel=${3:-}
# Where the booted Stage 2 records the partition UUID of its ESP.
device_tree_esp=${AURORA_DEVICE_TREE_ESP:-/proc/device-tree/chosen/asahi,efi-system-partition}
device_tree_compatible=${AURORA_DEVICE_TREE_COMPATIBLE:-/proc/device-tree/compatible}

refuse() {
  echo "aurora-install-stage2: $*; the ESP Stage 2 was left unchanged" >&2
  exit 1
}

# The board of a Mac that boots a Mach-O Stage 1, nothing on any other machine.
# The chips are the installer's: AuraStage1Format.usesMachO.
macho_board() {
  [[ -r $device_tree_compatible ]] || return 0
  local entry first=''
  while IFS= read -r -d '' entry; do
    [[ -n $first ]] || first=${entry#apple,}
    case $entry in
      apple,t81[3-9a-f]?|apple,t8[2-9a-f]??|apple,t60[4-9a-f]?|apple,t6[1-9a-f]??)
        echo "$first"
        return 0
        ;;
    esac
  done < "$device_tree_compatible"
}

[[ -n $source_dir && -n $esp ]] || refuse 'usage: install-stage2.sh STAGE2_DIR ESP_MOUNTPOINT'
board=''
if [[ -e $source_dir/monitor-free ]]; then
  board=$(macho_board)
fi
if [[ -n $board ]]; then
  source=$source_dir/ctxr/boot-ctxr-$board.bin
  name=boot-ctxr.bin
  if [[ ! -s $source || ! -f $source.sha256 ]]; then
    echo "aurora-install-stage2: warning: this build has no Stage 2 for $board, so m1n1/boot-ctxr.bin was left unchanged" >&2
    exit 0
  fi
else
  source=$source_dir/boot.bin
  name=boot.bin
  [[ -f $source && -s $source && -f $source.sha256 ]] || refuse "missing Stage 2 input $source"
fi
expected=$(<"$source.sha256")
[[ $expected =~ ^[0-9a-f]{64}$ ]] || refuse 'invalid Stage 2 digest record'
[[ $(sha256sum "$source" | cut -d' ' -f1) == "$expected" ]] || refuse 'the Stage 2 input does not match its digest'

mountpoint -q "$esp" || refuse "$esp is not mounted"
# The last entry is the file system on top at the mount point.
[[ $(findmnt -n -o FSTYPE --mountpoint "$esp" | tail -n 1) == vfat ]] || refuse "$esp is not a FAT ESP"
device=$(findmnt -n -o SOURCE --mountpoint "$esp" | tail -n 1)
if [[ -r $device_tree_esp ]]; then
  booted=$(tr -d '\000' < "$device_tree_esp" | tr '[:upper:]' '[:lower:]')
  mounted=$(lsblk -n -d -o PARTUUID "$device" | tr '[:upper:]' '[:lower:]')
  [[ -n $booted && $booted == "$mounted" ]] || refuse "$esp ($mounted) is not the ESP this Mac booted from ($booted)"
fi
[[ -d $esp/m1n1 ]] || refuse "$esp has no m1n1 directory"

export AURORA_STAGE2_DIR=$source_dir AURORA_STAGE2_SOURCE=$source AURORA_STAGE2_SHA256=$expected
export AURORA_TOPLEVEL=$toplevel AURORA_DEVICE_TREE_COMPATIBLE=$device_tree_compatible
export TARGET=$esp/m1n1/$name ESP_ROOT=$esp ESP_DEVICE=$device ESP_FSTYPE=vfat
exec "${AURORA_STAGE2_HELPER:-aurora-stage2}" install
