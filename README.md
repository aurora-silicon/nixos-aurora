# Aurora NixOS

NixOS modules and pinned Aurora hardware packages for Apple Silicon. The [native Aurora installer](https://github.com/aurora-silicon/aurora-installer) offers KDE Plasma, GNOME and minimal profiles.

The flake pins nixpkgs and the maintained [nixos-apple-silicon](https://github.com/nix-community/nixos-apple-silicon) module, then overlays Aurora's kernel, Mesa, Aura, U-Boot, audio profiles and services. `sources.json` records the same hardware source revisions used by the Fedora and ALARM ports. NixOS's declarative configuration, generations and rollback remain intact.

```sh
nix flake check --no-build
nix build .#checks.aarch64-linux.profiles
nix build .#aura .#uboot .#kernel .#mesa
```

`nixosConfigurations.aurora-kde`, `.aurora-gnome` and `.aurora-minimal` share the hardware module and kernel pin. Firmware is read from the target Mac's EFI partition at boot rather than embedded in a redistributable Nix store closure. No account password or device calibration is included in this repository.

Development status: all three profiles and hardware derivations evaluate; package builds, image production and physical installation are tracked separately. No installable NixOS image is released yet. CI builds on native AArch64 and records output closures. Do not treat source evaluation as hardware qualification.

A future installed configuration imports `nixosModules.default` alongside the pinned Apple Silicon module, uses `overlays.default`, and supplies the target machine's disk and account configuration. The checked image module describes the native installer's ESP + boot + root layout; it is not a configuration to apply to an unrelated existing machine.
