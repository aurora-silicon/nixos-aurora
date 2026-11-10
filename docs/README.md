# Documentation

## Configure and use Aurora

- [Module guide](modules.md): imports, desktop profiles, existing hosts and factory images.
- [Option reference](options.md): generated Aurora option types, defaults and descriptions.
- [Gaming](gaming.md): native Steam, FEX, Proton and Aurora Play.
- [Installed-system updates and recovery](updates.md#installed-systems): channels, rebuilds and Stage 2 rollback.
- [ANE setup](ane.md#nixos-firmware-handoff): optional tools and owner-supplied firmware.

## Maintain the repository

- [Development](development.md): repository layout, builds and checks.
- [Update and publication runbook](updates.md): source tracking, signed caches, channels and installer delivery.
- [Documentation maintenance](documentation.md): generate the option reference and check documentation.
- [Proton package notes](../pkgs/proton/README.md): source pins, Wine patch provenance and runtime limits.

## Reference and investigation notes

These pages retain the pins, PR states and verification recorded during their
investigations. Treat those details as snapshots; current package inputs are in
[`sources.json`](../sources.json), [`flake.lock`](../flake.lock) and the package recipes.

- [Fedora parity, 28–29 October 2026](fedora-parity-20261029.md).
- [Fedora merge sweep, 31 October 2026](fedora-parity-20261031.md), with its [merge inventory](fedora-merges-20261031.json).
- [Userspace package parity, 31 October 2026](userspace-parity.md).
- [AVD firmware changelog](avd-fw.md): the 1 November 2026 firmware updates.
- [Universal kernel configuration](universal-kernel-config.md): resolved-config inheritance and source/config contracts.
- [Userspace boot defaults](clean-boot-userspace.md): BlueZ, Docker, swap ordering and cross-distribution workaround retirement.
- [Native GL qualification draft](native-gl-default.md): driver-selection policy, qualification requirements and migration.
- [UPower 1.91.5 candidate notes](upower-1.91.5.md): cross-distribution packaging, read-only battery checks and rollback.
- [ANE packaging notes](ane.md): package contents, fixture provenance and source redistribution.
