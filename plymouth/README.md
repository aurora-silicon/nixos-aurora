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
