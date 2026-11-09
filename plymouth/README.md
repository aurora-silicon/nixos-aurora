# Plymouth carries

Append the production patch from
[Fedora carry #111](https://github.com/aurora-silicon/fedora-aurora/pull/111)
to nixpkgs' existing Plymouth patches. The patch and GPL-2.0-or-later PTY
regression are copied unchanged from the merged Fedora carry
`365f64902977d8b59de166722b2a3ef9ea1ae94d`. The nixpkgs source version and
its existing patches and hooks are retained.

The overlay keeps terminal keyboard reads nonblocking using an independent
input descriptor while preserving blocking terminal output. `doCheck` enables
`postCheck`, which compiles the PTY regression against the libraries just
built and bounds it to 15 seconds. It exercises stale readiness, termios
changes, partial and complete canonical lines, close/reopen cleanup, and the
real keyboard input handler without a physical console.

## Frame-buffer race and XKB keymap fallback

Fedora's Plymouth 26.134.222 recipe carries two upstream fixes that nixpkgs
does not. The overlay applies them first, in Fedora's order, copied unchanged
from fedora-aurora `packages/plymouth`:

- `0001-ply-device-manager-Fix-race-in-fb_device_has_drm_dev.patch`: when udev
  restarts on the real root, plymouth gets an add event for the fbdev of the
  DRM device whose splash it already shows. Its udev query for a matching DRM
  card could run before udev had enumerated that card, so plymouth loaded the
  frame-buffer plugin and opened the same output a second time through fbdev.
  The fix recognises DRM-emulated fbdevs by their `drmfb` name instead.
- `0001-ply-device-manager-fix-default-XKB-keymap-fallback-o.patch`
  (upstream `cea90be39d26`): the default XKB keymap no longer overrides the
  console `KEYMAP`, so the passphrase prompt uses the configured layout.

All six patches apply with no fuzz to the 26.134.222 tag after nixpkgs' own
patches. The firstboot flake check requires both on every profile.

## SDR display handoff

The overlay also appends
`0002-drm-Reset-inherited-HDR-connector-state-before-SDR.patch` and runs
the GPL-2.0-or-later `test-drm-sdr.c` regression, both copied unchanged from
[Fedora carry #159](https://github.com/aurora-silicon/fedora-aurora/pull/159),
merged as `7dc345041f935449a706415cc7518dccdb691aaf`. The patch applies
cleanly to nixpkgs' 26.134.222 with its existing patches.

Plymouth's DRM renderer draws SDR pixels and presents them with legacy
`drmModeSetCrtc()`, which keeps the previous DRM master's connector
`HDR_OUTPUT_METADATA` and `Colorspace`. A compositor can drop master before
closing its file, so the reboot or shutdown splash could inherit PQ/BT.2020
and show a blown out logo. The patch clears both properties on the head's
connectors, clones included, in one blocking atomic commit before setting
the scanout buffer. A failed reset leaves scanout for a later retry, each
activation rechecks, and drivers without atomic support keep the legacy
path. The compositor restores its own HDR state when it takes control again.

`postCheck` compiles the DRM regression against the renderer source and the
libraries just built, with libdrm mocked, and bounds it to 15 seconds. It
checks that no SDR framebuffer is presented while either inherited property
is set, that clones reset together, that unrelated properties and connectors
are left alone, and covers SDR redraws, missing properties, legacy drivers,
allocation/query/commit failures and retry. No DRM device is required. The
firstboot flake check also requires this patch on every profile's Plymouth.

Build and test with `nix build -L .#plymouth` on aarch64-linux. Aurora's module
selects the overlay package through `boot.plymouth.package`; the firstboot
flake check verifies that KDE, GNOME and minimal configurations all select
the patched derivation. After upgrading, rebuild the boot generation to put
the patched libraries in the initrd. Retire the carry when nixpkgs includes
an equivalent upstream fix.

## Script keyboard lifetime and theme 1-4

The same carry also applies `0001-Fix-splash-keyboard-lifetime.patch`, copied
unchanged from the Ryan-authored t-4476 implementation. It notifies consumers
before freeing renderer keyboards, updates the script library on replacement
and detach, and preserves input handler ownership across hide/show. Removing
theme caps-lock polling alone cannot make the hide path safe.

`check-keyboard-lifetime.sh` runs native query and renderer-removal fixtures
against the just-built libraries and private X11/label modules under Xvfb.
The renderer fixture uses a private PTY and requires no hardware console.
The original terminal-input PTY regression remains enabled.

The combined derivation has release suffix `-aurora3` and exposes
`scriptKeyboardLifetime = 1`. Theme 1-4 asserts that capability >= 1, and all
Aurora profiles select the same patched Plymouth derivation.

Public GPL-2.0-or-later implementation sources are Plymouth
[24.004.60](https://gitlab.freedesktop.org/plymouth/plymouth/-/tree/d6e6366d622962dce02d8c7e4ab814f54a202509)
and [26.134.222](https://gitlab.freedesktop.org/plymouth/plymouth/-/tree/1aacf818fd5d1b6a7695546eb08fcbc46893dd0b).
Install the matching core and theme together and rebuild the initramfs or
NixOS boot generation. Preserve the previous packages, configuration and
initramfs or generation, and restore them together to roll back.

The installed descriptor uses NixOS's merged `/run/plymouth/themes/spinner`
directory, so the script can resolve both spinner images and Aurora's sibling
logo PNGs. Its dependent-theme marker keeps NixOS's initrd asset discovery.
Plymouth always prefixes image filenames with `ImageDir`; pointing at the
core store output would miss Aurora's sibling directory on the real root.
The geometry and script are still generated only into `/run` at startup.
