#!/bin/bash
# usage: inspect-initrd.sh TOPLEVEL...  (prints plymouth-start ordering and early-kms presence)
for t in "$@"; do
  echo "== $t"; cat "$t/kernel-params"; echo
  d=$(mktemp -d)
  (cd "$d" && nix shell nixpkgs#zstd nixpkgs#cpio -c sh -c "zstd -dc < '$t/initrd' | cpio -id --quiet")
  for u in $(find "$d" -name plymouth-start.service); do echo "${u#$d}"; grep -E '^(After|Before)' "$(readlink -f "$u" | sed "s|^/nix|$d/nix|")" 2>/dev/null || grep -E '^(After|Before)' "$u"; done
  find "$d" -name 'aurora-early-kms*' | sed "s|$d||"
  ls "$d/etc/systemd/system/sysinit.target.wants" 2>/dev/null | tr '\n' ' '; echo
  rm -rf "$d"
done
