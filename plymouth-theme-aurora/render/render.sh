#!/bin/bash
# SPDX-License-Identifier: MIT
# Render real Plymouth script-plugin output under Xvfb, without a target.
# Usage: P=/usr THEME=/w/theme render.sh OUTPUT_DIRECTORY
set -euo pipefail
O=${1:-/w/out/render}; mkdir -p "$O"
P=${P:-/usr}
THEME=${THEME:-/w/theme}
T=/usr/share/plymouth/themes/aurora
confdir=$P/etc/plymouth
if [[ $P == /usr ]]; then confdir=/etc/plymouth; fi
mkdir -p "$T" "$P/share/plymouth/themes" "$confdir"
cp "$THEME"/aurora.plymouth "$THEME"/aurora.script "$THEME"/aurora-logo-*.png "$T/"
if [[ $P != /usr ]]; then
  export LD_LIBRARY_PATH="$P/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  ln -sfn "$T" "$P/share/plymouth/themes/aurora"
  ln -sfn /usr/share/plymouth/themes/spinner "$P/share/plymouth/themes/spinner"
fi
printf '[Daemon]\nTheme=aurora\nShowDelay=0\nDeviceScale=1\n' > "$confdir/plymouthd.conf"
: > "$O/measurements.jsonl"

shot() { # name mode-width mode-height panel-width panel-height notch [fixture flags]
  local n=$1 w=$2 h=$3 pw=$4 ph=$5 notch=$6; shift 6
  local dt="$O/$n.dt" xp pp display
  python3 "$THEME/test_geometry.py" --fixture "$dt" "$pw" "$ph" "$notch" "$@"
  sh "$THEME/aurora-plymouth" "$T" /run/plymouth/aurora.script "$dt"
  head -4 /run/plymouth/aurora.script > "$O/$n.geometry"
  Xvfb -displayfd 3 -screen 0 "${w}x${h}x24" -nolisten tcp 3>"$O/display" >"$O/$n.xvfb.log" 2>&1 & xp=$!
  for ((i=0; i<100; i++)); do [[ -s "$O/display" ]] && break; sleep .1; done
  display=:$(cat "$O/display")
  DISPLAY=$display "$P/sbin/plymouthd" --no-daemon --debug --debug-file="$O/$n.log" \
    --kernel-command-line="splash quiet plymouth.ignore-udev" --mode=boot >"$O/$n.stdout" 2>&1 & pp=$!
  trap 'kill "${pp:-}" "${xp:-}" 2>/dev/null || true' RETURN
  sleep 1
  "$P/bin/plymouth" show-splash
  sleep 2
  xwd -root -display "$display" -silent | magick xwd:- "$O/$n.png"
  magick "$O/$n.png" -depth 8 "rgb:$O/$n.rgb"
  "$P/bin/plymouth" hide-splash
  "$P/bin/plymouth" show-splash
  "$P/bin/plymouth" quit
  wait "$pp"
  kill "$xp"; wait "$xp" 2>/dev/null || true
  trap - RETURN
  python3 /w/render/measure.py "$T/aurora-logo-128.png" "$T/aurora-logo-256.png" \
    "$O/$n.rgb" "$w" "$h" --panel "$pw" "$ph" "$notch" --size "${SIZE:-256}" | tee -a "$O/measurements.jsonl"
  rm -rf "$dt"; rm "$O/$n.rgb" "$O/display"
}

# The same platform metadata must work before and after appledrm takeover.
shot j616s-cropped 3456 2160 3456 2234 74
shot j616s-full 3456 2234 3456 2234 74
shot j616s-loader-full 3456 2234 3456 2234 74 --full
shot j616s-no-dcp-property 3456 2160 3456 2234 74 --omit-notch
shot m2-cropped 2560 1600 2560 1664 64
shot m2-full 2560 1664 2560 1664 64
shot m2-loader-full 2560 1664 2560 1664 64 --full
shot neo-cropped 2408 1506 2408 1506 0
shot neo-full 2408 1506 2408 1506 0 --full
shot odd-notch-cropped 2560 1600 2560 1665 65
# Other display modes use their own centre, even at the cropped panel height.
shot other-width 2400 2160 3456 2234 74
shot other-height 3456 2100 3456 2234 74
SIZE=128 shot external-1080p 1920 1080 1920 1080 0
SIZE=128 shot external-4k 3840 2160 3840 2160 0
