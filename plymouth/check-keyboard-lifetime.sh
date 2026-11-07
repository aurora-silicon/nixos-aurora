#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Usage: check-keyboard-lifetime.sh PREPARED_SOURCE BUILD TEST_SOURCE_DIR
set -euo pipefail
src=$(realpath "$1")
build=$(realpath "$2")
tests=$(realpath "$3")
case ${KEYBOARD_TEST_CASE:-all} in all|script|removal) ;; *) exit 2 ;; esac
work=$(mktemp -d)
trap 'if [[ -n ${xpid:-} ]]; then kill "$xpid" 2>/dev/null || :; wait "$xpid" 2>/dev/null || :; fi; rm -rf "$work"' EXIT
mkdir -p "$work/plugins/renderers"
ln -s "$build/src/plugins/renderers/x11/x11.so" "$work/plugins/renderers/x11.so"
for module in "$build"/src/plugins/controls/*/*.so; do
    [[ -f $module ]] || continue
    ln -s "$module" "$work/plugins/${module##*/}"
done
cat > "$work/query.script" <<'SCRIPT'
fun refresh() { global.capslock = Plymouth.GetCapslockState(); }
Plymouth.SetRefreshFunction(refresh);
SCRIPT
cat > "$work/theme.plymouth" <<THEME
[Plymouth Theme]
Name=Keyboard lifetime regression
ModuleName=script
[script]
ImageDir=/
ScriptFile=$work/query.script
THEME
# Link to the libraries being tested, with their renderer implementation
# pointed at the just-built X11 module rather than any installed package.
# Use a private config header so config.h cannot replace a command-line
# plugin path with the installed system path.
sed "s|^#define PLYMOUTH_PLUGIN_PATH .*|#define PLYMOUTH_PLUGIN_PATH \"$work/plugins/\"|" "$build/config.h" > "$work/config.h"
common=(-I"$work" -include "$work/config.h" -D_GNU_SOURCE -g -O0 -I"$build" -I"$src" -I"$src/src/libply" -I"$src/src/libply-splash-core" -I"$src/src/libply-splash-graphics")
if grep -q extra_esc_key "$src/src/libply-splash-core/ply-device-manager.h"; then
    common+=(-DHAVE_DEVICE_MANAGER_EXTRA_ESC_KEY)
fi
libs=(-L"$build/src/libply" -L"$build/src/libply-splash-core" -L"$build/src/libply-splash-graphics" -lply-splash-graphics -lply-splash-core -lply -lm -ldl)
export LD_LIBRARY_PATH="$build/src/libply:$build/src/libply-splash-core:$build/src/libply-splash-graphics${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
${CC:-cc} "${common[@]}" -I"$src/src/libply-splash-core" \
    "$tests/test-keyboard-lifetime.c" "$src/src/libply-splash-core/ply-renderer.c" \
    "$src/src/libply-splash-graphics/ply-label.c" \
    -o "$work/test-removal" "${libs[@]}" $(pkg-config --cflags --libs libudev xkbcommon libevdev)
objects=()
for object in "$build/src/plugins/splash/script/script.so.p/"*.o; do
    [[ $(basename "$object") == plugin.c.o ]] || objects+=("$object")
done
${CC:-cc} "${common[@]}" -I"$src/src/plugins/splash/script" -I"$build/src/plugins/splash/script" \
    "$tests/test-script-keyboard.c" "${objects[@]}" -o "$work/test-script" "${libs[@]}"
if [[ ${KEYBOARD_TEST_CASE:-all} != removal ]]; then
    "$work/test-script" "$work/query.script"
fi
[[ ${KEYBOARD_TEST_CASE:-all} != script ]] || exit 0
# -displayfd selects an unused display number, including concurrent builds.
Xvfb -displayfd 3 -screen 0 1024x768x24 -nolisten tcp 3>"$work/display" >"$work/xvfb.log" 2>&1 &
xpid=$!
for ((i=0; i<100; i++)); do
    [[ -s "$work/display" ]] && break
    sleep 0.1
done
[[ -s "$work/display" ]] || { cat "$work/xvfb.log"; exit 1; }
export DISPLAY=:$(cat "$work/display")
if [[ -n ${KEYBOARD_THEME:-} ]]; then
    theme=$KEYBOARD_THEME
else
    theme=$work/theme.plymouth
fi
"$work/test-removal" "$theme" "$build/src/plugins/splash/script/"
