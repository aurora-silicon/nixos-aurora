#!/bin/bash
# Build a NixOS aarch64 UEFI disk image with a LUKS2 root from a built
# system toplevel. Runs in the Lima arm64 guest (needs sudo).
# usage: build-image.sh VARIANT   (test|control; flake in this directory)
set -euo pipefail
D=$(cd "$(dirname "$0")" && pwd)
V=$1
PASS=aurora-luks-test
LUKS_UUID=5e1f0c7a-0a7e-4c55-9d6b-4a2c1f3b9e01
cd "$D"
SYS=$(nix build --no-link --print-out-paths ".#nixosConfigurations.$V.config.system.build.toplevel")
TOOLS=$(nix build --no-link --print-out-paths nixpkgs#nixos-install-tools)
CS=$(nix build --no-link --print-out-paths nixpkgs#cryptsetup.bin 2>/dev/null || nix build --no-link --print-out-paths nixpkgs#cryptsetup)
CRYPT=$(ls "$CS"/bin/cryptsetup 2>/dev/null || ls "$(nix eval --raw nixpkgs#cryptsetup.outPath)"/bin/cryptsetup)
NIX=$(dirname "$(command -v nix)")
IMG="$D/$V.raw"
MNT=/var/tmp/nixos-luks-$V
MAP=nixluks-$V
rm -f "$IMG"; truncate -s 6G "$IMG"
sfdisk -q "$IMG" <<'PT'
label: gpt
size=256MiB, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, name=ESP
type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name=root
PT
sudo -E bash -euo pipefail -c '
IMG=$1; MNT=$2; MAP=$3; CRYPT=$4; PASS=$5; UUID=$6; SYS=$7; TOOLS=$8; NIX=$9
LOOP=$(losetup -fP --show "$IMG")
cleanup() { umount -R "$MNT" 2>/dev/null || true; "$CRYPT" close "$MAP" 2>/dev/null || true; losetup -d "$LOOP" || true; }
trap cleanup EXIT
mkfs.vfat -F 32 -n ESP -i AE012026 "${LOOP}p1" >/dev/null
printf "%s" "$PASS" | "$CRYPT" luksFormat --type luks2 --uuid "$UUID" --pbkdf pbkdf2 --pbkdf-force-iterations 100000 --batch-mode "${LOOP}p2" -
printf "%s" "$PASS" | "$CRYPT" open "${LOOP}p2" "$MAP" --key-file -
mkfs.ext4 -q -L nixos "/dev/mapper/$MAP"
mkdir -p "$MNT"; mount "/dev/mapper/$MAP" "$MNT"
mkdir -p "$MNT/boot"; mount "${LOOP}p1" "$MNT/boot"
PATH="$TOOLS/bin:$NIX:$PATH:/run/current-system/sw/bin" nixos-install --system "$SYS" --root "$MNT" --no-root-passwd --no-channel-copy
ls -R "$MNT/boot" | head -40
cp "$MNT/boot/grub/grub.cfg" "$(dirname "$IMG")/$(basename "$IMG" .raw)-grub.cfg"
' bash "$IMG" "$MNT" "$MAP" "$CRYPT" "$PASS" "$LUKS_UUID" "$SYS" "$TOOLS" "$NIX"
echo IMAGE-OK "$V" "$SYS"
