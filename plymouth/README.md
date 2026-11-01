# Plymouth terminal input carry

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

Build and test with `nix build -L .#plymouth` on aarch64-linux. Aurora's module
selects the overlay package through `boot.plymouth.package`; the firstboot
flake check verifies that KDE, GNOME and minimal configurations all select
the patched derivation. After upgrading, rebuild the boot generation to put
the patched libraries in the initrd. Retire the carry when nixpkgs includes
an equivalent upstream fix.
