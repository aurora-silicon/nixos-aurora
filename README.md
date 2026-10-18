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


Native local hardware builds now pass for Aura, U-Boot, the shared 7.2.10 kernel, Mesa, speakerguardd, Bankstown, Neo network configuration and aurora-bless. The kernel uses LLVM 22.1.8: an identical-input relink isolated invalid DWARF section references in lld 21, while lld 22 preserves them and passes BTF generation. Mesa uses Clang at normal release optimization, retaining all tests and the two-stage compiler-tool build; its driver closure excludes LLVM and SPIRV-Tools. These are build results, not device qualification.

`modules/platform.nix` wires the J700 guardian through its sense-PCM udev rule, retains feedback protection on other Macs, and enables Bluetooth userspace and the wireless regulatory database. The firmware helper checks this Mac's calibration/radio inputs before admission and defers Bluetooth until the runtime service before BlueZ.

The signed cache tools are `scripts/export-cache` and `scripts/prepare-cache-publication.py`. Private keys enter only through a supplied signing-key descriptor, never through an exported artifact directory. Cache clients verify signed NAR identities independently of their transport URLs. The public key is `keys/cache.pub`; publication and image qualification remain separate operations.

For an incremental snapshot, supply the last deployed cache directory with `--previous-metadata`. The preparer retains older entries and reuses their immutable Aurora release URLs only when the signed store identity and compressed transport identity match exactly. The current export's signatures are retained. Only new NAR files appear in the output `assets` directory; manifest rows with `reused_from` identify retained transport assets. Upload the actual files in `assets`, including the merged metadata archive, to the new release. The deployment workflow verifies every signed entry and its full NAR over HTTP, including reused assets, before replacing the public cache. Keep older releases available.
