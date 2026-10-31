# Mutter 51 packaging

GNOME publishes [Mutter 51.1](https://download.gnome.org/sources/mutter/51/) as the
current 51.x release. Its tag resolves to `9134e3a5869ce232bf95b77519005865747ba603`;
the release archive SHA-256 is
`0d311d87901dbcb94518fb89304febe30852ce5d8a4befa9f87e85c68eceefde`.
The archive and the tag are distinct source identities.

| Patch | 51.1 decision | Provenance |
| --- | --- | --- |
| Prefer the variable variant of the preferred KMS mode | Keep unchanged; upstream still prefers the fixed variant | [Aurora PR 41](https://github.com/aurora-silicon/fedora-aurora/pull/41) |
| Reject touch grabs when the focus surface is null | Keep unchanged; the guard is absent in 51.1 | [GNOME MR 5375](https://gitlab.gnome.org/GNOME/mutter/-/merge_requests/5375), commit `13ed6caed4580d6d1ee8812a4d180ea8b5035ddc` |

The former `51.0-1.fc45.aurora.vrr1` test build is documented in
[PR 41's hardware result](https://github.com/aurora-silicon/fedora-aurora/pull/41#issuecomment-6487454438).
That records the same VRR hunk on Fedora's 51.0 package. It proves mode selection,
including the MSI 280 Hz variable mode; it does not prove VRR activation.
An exact build tree and original binary identity are not established by that comment.

Fedora's `packages/mutter/f45/mutter.spec` builds 51.1 with API/SONAME 51 and both patches.
`51.1-2.fc45.aurora` sorts above Fedora's `51.1-1.fc45` and the former 51.0 test
build without an epoch; later upstream versions can still supersede it.
The minimum schemas, Wayland, protocols, libinput and PipeWire versions follow
51.1's Meson requirements. The experimental settings schema is packaged too.

Run `AURORA_INSTALL_BUILDDEPS=1 AURORA_BUILD_JOBS=8 bash scripts/build-mutter-51`
inside a Fedora 45 arm64 container with rpm-build and dnf5-plugins installed.
The dedicated `Mutter 51 Fedora 45` workflow runs this natively and retains RPMs,
SRPM, recipe manifest, build log and Meson test logs, including on failure.
The default unprivileged Mutter, Clutter, Cogl and tool suites run with Xvfb and
software rendering. KMS/TTY and KVM tests are outside this arm64 builder.

The existing parent recipe, root sources.json pin and Fedora 44 publication stay
on GNOME 50. Fedora 45 candidates have a separate output directory and workflow
so a 51 SONAME cannot replace the Fedora 44 release's compositor. Shipping these
in a Fedora 45 channel requires the Fedora release migration; upgrading a Fedora
44 GNOME Shell to Mutter 51 alone is not supported.

Arch uses `mutter-aurora` 51.1 and NixOS uses the GNOME 51 package set plus the same
51.1 release archive. Both must carry the two patches above. GNOME Shell and its
schemas must agree with API 51; changing only the Mutter source on NixOS's former
GNOME 50 package set cannot provide a working desktop.

For device qualification, retain original RPMs and monitor settings, install all
Mutter subpackages in one DNF transaction, restart GDM, and verify GNOME Shell
loads libmutter-51. Test both a saved monitor configuration and a fresh one.
Inspect the KMS `VRR_ENABLED` property during a fullscreen scanout candidate and
after leaving fullscreen; a `+vrr` mode selection alone is insufficient.
Rollback with exact saved RPMs or an explicitly selected stock Fedora NEVRA for
all installed Mutter subpackages, then restart GDM and verify again.

## NixOS integration

The locked nixpkgs input moves to `d27eeb635b2c5fe835604bb747f6bfb722ae6e7d`,
the GNOME 51 staging-next revision checked on 2026-10-31. It includes
[nixpkgs' GNOME 51 update](https://github.com/NixOS/nixpkgs/pull/559510).
This keeps Shell 51.0, schemas 51 and the Mutter 51 ABI coherent. The overlay
pins Mutter to 51.1 using the archive hash above and enables the unprivileged
upstream suites. `mutter` and `gnome-shell` are explicit flake outputs so CI
builds both sides of the compositor interface. `checks.aarch64-linux.mutter-51`
checks the API, schemas, Shell major version and installed Mutter library path.

This nixpkgs pin also removes the scripted initrd. Aurora already uses the
systemd initrd, so the two removed options (`boot.initrd.systemd.enable` and
`boot.initrd.verbose`) are no longer defined. Firmware service ordering and
store paths are retained unconditionally. All three NixOS profiles must still
pass evaluation and first-boot configuration checks before this is ready.

Build with `nix build --print-build-logs .#mutter .#gnome-shell`; inspect the
Mutter build/test log with `nix log .#mutter`. Install a tested GNOME system
configuration through `nixos-rebuild switch`, and roll back with
`nixos-rebuild switch --rollback`. Retain the previous system generation.
