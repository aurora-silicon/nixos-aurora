# Aurora NixOS

NixOS modules and pinned Aurora hardware packages for Apple Silicon. The [native Aurora installer](https://github.com/aurora-silicon/aurora-installer) offers KDE Plasma, GNOME and minimal profiles.

The flake pins nixpkgs and the maintained [nixos-apple-silicon](https://github.com/nix-community/nixos-apple-silicon) module, then overlays Aurora's kernel, Mesa, Aura, U-Boot, audio profiles and services. `sources.json` records the same hardware source revisions used by the Fedora and ALARM ports. NixOS's declarative configuration, generations and rollback remain intact.

```sh
nix flake check --no-build
nix build .#checks.aarch64-linux.profiles
nix build .#aura .#uboot .#kernel .#mesa
```

`nixosConfigurations.aurora-kde`, `.aurora-gnome` and `.aurora-minimal` share the hardware module and kernel pin. Firmware is read from the target Mac's EFI partition at boot rather than embedded in a redistributable Nix store closure. No account password or device calibration is included in this repository.

Development status: KDE, GNOME and minimal development installer payloads and a signed binary cache are published. The refreshed kernel, AVD firmware and UPower changes are being qualified separately. Physical installation, encrypted first boot and device update/reboot validation remain pending. CI builds on native AArch64 and records output closures. Source evaluation and published artifacts do not establish hardware qualification.

A future installed configuration imports `nixosModules.default` alongside the pinned Apple Silicon module, uses `overlays.default`, and supplies the target machine's disk and account configuration. The checked image module describes the native installer's ESP + boot + root layout; it is not a configuration to apply to an unrelated existing machine.


Native local hardware builds now pass for Aura, U-Boot, the shared 7.2.10 kernel, Mesa, speakerguardd, Bankstown, Neo network configuration and aurora-bless. The kernel uses LLVM 22.1.8: an identical-input relink isolated invalid DWARF section references in lld 21, while lld 22 preserves them and passes BTF generation. Mesa uses Clang at normal release optimization, retaining all tests and the two-stage compiler-tool build; its driver closure excludes LLVM and SPIRV-Tools. These are build results, not device qualification.

`modules/platform.nix` wires the J700 guardian through its sense-PCM udev rule, retains feedback protection on other Macs, and enables Bluetooth userspace and the wireless regulatory database. The firmware helper checks this Mac's calibration/radio inputs before admission and defers Bluetooth until the runtime service before BlueZ.

The cache tools are `scripts/export-cache` (an unsigned export of a build's closure), `scripts/sign-cache-metadata.py` (signs narinfo metadata in the publisher's protected job) and `scripts/prepare-cache-publication.py`. No build job holds the signing key. Cache clients verify signed NAR identities independently of their transport URLs. The public key is `keys/cache.pub`; publication and image qualification remain separate operations.

For an incremental snapshot, supply the last deployed cache directory with `--previous-metadata`. The preparer retains older entries and reuses their immutable Aurora release URLs only when the signed store identity and compressed transport identity match exactly. The current export's signatures are retained. Only new NAR files appear in the output `assets` directory; manifest rows with `reused_from` identify retained transport assets. Upload the actual files in `assets`, including the merged metadata archive, to the new release. The deployment workflow verifies every signed entry and its full NAR over HTTP, including reused assets, before replacing the public cache. Keep older releases available.

`publish-cache.yml` automates that preparation on native AArch64. It finds the newest cache release and the eligible native builds itself (explicit build IDs, base and tag remain optional inputs). The collector evaluates the committed Git flake, accepts only matching derivations and complete output sets from main-branch builds or manual builds whose commits have since been merged, verifies CI artifact digests and Nix signatures, and requires coverage of every current hardware output. It imports one bounded artifact at a time and retires extracted duplicates after verified merging. Run `deploy-cache.yml` for the resulting tag to verify the immutable HTTP assets before activating the cache; then build the desktop images.

The hardware stack includes the pinned Aurora AVD firmware and UPower forks. All decoder variants are built with their linked symbols in a separate `debug` output. UPower retains the upstream NixOS service and client contracts and runs the fork's macsmc regression tests. The shared 7.2.10 kernel also carries the accepted M4+ wait-state fix.

Source tracking, automatic publication, the `channel-testing` and `channel-stable` refs and the signing environments are described in [docs/updates.md](docs/updates.md).

Installed systems follow `channel-testing` (their `flake.lock` pins the installed commit). `sudo aurora-update` takes the newest signed update; every rebuild refreshes the ESP Stage 2 the way `update-m1n1` does on ALARM and Fedora, keeping `m1n1/boot.bin.old`, and never writes Stage 1. Nothing updates unattended. Installs from images before Alpha 9 need a one-time `flake.nix` edit, described in [docs/updates.md](docs/updates.md#moving-an-existing-install-to-the-channel-one-time).
