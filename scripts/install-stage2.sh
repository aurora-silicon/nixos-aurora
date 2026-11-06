#!/usr/bin/env bash
# Install the Stage 2 on this Mac's ESP the way update-m1n1 does on ALARM and
# Fedora: write it only when it changes and keep the previous file as .old.
# M1 to M3 Macs use the combined m1n1/boot.bin. A Mac that boots a Mach-O
# Stage 1 uses m1n1/boot-ctxr.bin with only its board's device trees, and its
# m1n1/boot.bin is never touched. It writes nothing else on the ESP, Stage 1
# included, and it refuses (leaving the ESP as it was) when an input is
# missing, the input does not match its recorded digest, the ESP is not the
# mounted FAT partition this Mac booted from, or the written copy does not
# verify.
#
#   install-stage2.sh STAGE2_DIR ESP_MOUNTPOINT
#
# STAGE2_DIR holds boot.bin, ctxr/boot-ctxr-<board>.bin and a .sha256 beside
# each, from the checked build.
set -euo pipefail

source_dir=${1:-}
esp=${2:-}
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
board=$(macho_board)
if [[ -n $board ]]; then
  source=$source_dir/ctxr/boot-ctxr-$board.bin
  name=boot-ctxr.bin
else
  source=$source_dir/boot.bin
  name=boot.bin
fi
[[ -f $source && -s $source && -f $source.sha256 ]] || refuse "missing Stage 2 input $source"
expected=$(<"$source.sha256")
[[ $expected =~ ^[0-9a-f]{64}$ ]] || refuse 'invalid Stage 2 digest record'
[[ $(sha256sum "$source" | cut -d' ' -f1) == "$expected" ]] || refuse 'the Stage 2 input does not match its digest'

mountpoint -q "$esp" || refuse "$esp is not mounted"
# The last entry is the file system on top at the mount point.
[[ $(findmnt -n -o FSTYPE --mountpoint "$esp" | tail -n 1) == vfat ]] || refuse "$esp is not a FAT ESP"
if [[ -r $device_tree_esp ]]; then
  booted=$(tr -d '\000' < "$device_tree_esp" | tr '[:upper:]' '[:lower:]')
  device=$(findmnt -n -o SOURCE --mountpoint "$esp" | tail -n 1)
  mounted=$(lsblk -n -d -o PARTUUID "$device" | tr '[:upper:]' '[:lower:]')
  [[ -n $booted && $booted == "$mounted" ]] || refuse "$esp ($mounted) is not the ESP this Mac booted from ($booted)"
fi
[[ -d $esp/m1n1 ]] || refuse "$esp has no m1n1 directory"

target=$esp/m1n1/$name
if [[ -f $target ]] && cmp -s "$source" "$target"; then
  exit 0
fi
staged=$target.new
rm -f "$staged"
cp "$source" "$staged"
sync "$staged"
if [[ $(sha256sum "$staged" | cut -d' ' -f1) != "$expected" ]]; then
  rm -f "$staged"
  refuse 'the copy written to the ESP does not verify'
fi
if [[ -f $target ]]; then
  cp --preserve=timestamps -f "$target" "$target.old"
fi
mv -f "$staged" "$target"
sync "$target"
echo "Stage 2 updated at $target; the previous one is m1n1/$name.old"
