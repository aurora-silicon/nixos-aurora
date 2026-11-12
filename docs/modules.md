# Modules and configuration

Use Aurora's pinned Nixpkgs and Apple Silicon inputs together with its overlay.
The [option reference](options.md) lists the Aurora settings, defaults and
examples. Standard NixOS settings still control accounts, disks and services.
For standard options, use the [NixOS reference](https://search.nixos.org/options)
and the [Apple Silicon module reference](https://github.com/nix-community/nixos-apple-silicon).

## Exported modules

| Module | Purpose |
| --- | --- |
| `aurora.nixosModules.default` | The shared Apple Silicon system: hardware services, desktop selection, graphics, audio, firmware handoff and the internal modules below. Requires the Apple Silicon module and both overlays. |
| `aurora.nixosModules.installed` | Checked Stage 2 updates on bootloader installation, plus `aurora-update` and `aurora-install-stage2`. Use with `default` on an installer-provisioned Mac; it supplies no disk layout or accounts. `aurora.stage2.*` controls Stage 2 updates. |
| `aurora.nixosModules.image` | The native installer's Btrfs root/home, ext4 boot and FAT ESP layout, image filesystem identities, mutable accounts and initial `system.stateVersion`. Use for Aurora installer images, alongside the other two modules. |

`default` selects KDE unless `aurora.desktop` is changed to `gnome` or
`minimal`. It does not import `image` or `installed` for you. The exported
`aurora-kde`, `aurora-gnome` and `aurora-minimal` configurations import all three
and describe installer images.

`default` also enables GRUB/EFI, NetworkManager, graphics and fingerprint
services. Use `overlays.default` alone for packages without those system
settings. Settings declared with `mkDefault` accept ordinary overrides;
replacing fixed standard NixOS settings can require `lib.mkForce`.

## Existing system

Keep the Mac's existing filesystem declarations, accounts and initial
`system.stateVersion`. Do not import `image` to reuse the hardware stack on an
existing layout. This example uses Aurora's own input versions and the same
module/overlay order as the installer-generated flake:

```nix
{
  inputs.aurora.url = "github:aurora-silicon/nixos-aurora/channel-testing";

  outputs = { aurora, ... }: {
    nixosConfigurations.aurora = aurora.inputs.nixpkgs.lib.nixosSystem {
      system = "aarch64-linux";
      modules = [
        aurora.inputs.apple-silicon.nixosModules.default
        aurora.nixosModules.default
        aurora.nixosModules.installed
        ./hardware-configuration.nix
        ./host.nix
        {
          nixpkgs.overlays = [
            aurora.inputs.apple-silicon.overlays.default
            aurora.overlays.default
          ];
          aurora.desktop = "minimal";
        }
      ];
    };
  };
}
```

`hardware-configuration.nix` and `host.nix` are your machine's configuration,
including its mounts, accounts and original state version. Leave
`aurora.imageLayout` unset for an existing layout. The Apple Silicon installer
must already have provisioned the Mac's boot environment.

The input follows the testing channel; `flake.lock` pins the selected commit.
Set `aurora.update.flake = "/etc/nixos#aurora";` in `host.nix` for updates of
this consumer flake, or first run `sudo aurora-update --flake /etc/nixos#aurora`.
The latter remembers its source only after a successful local switch, for that
system generation. Direct `nixos-rebuild` does not record the original source;
use the declarative option for that workflow. `aurora.update.inputName` defaults
to `aurora`. Updates do not run unattended. Stage 2 uses trial-then-commit updates
when Stage 1 supports them, with CTXR selection and retained-generation DT ABI checks.
Stage 1 stays unchanged. See [updates and recovery](updates.md#stage-2-on-rebuild).

## Kernel source overrides

When overriding the kernel source, retain its revision in `src.rev`, as
`fetchFromGitHub` and `fetchgit` do. For a fixed-output archive, add that metadata
explicitly:

```nix
kernel.override {
  src = (pkgs.fetchurl {
    url = "https://example.org/linux-COMMIT.tar.gz";
    hash = "sha256-...";
  }) // { rev = "COMMIT"; };
}
```

The kernel exposes `auroraSourceCommit` and writes the revision to
`aurora-source-commit`; the parity manifest follows the selected kernel.
An archive without `rev` records `unknown` and a null manifest revision, which
the installer parity check rejects. Source metadata does not establish hardware
compatibility or replace a matching kernel configuration.

## First boot and everyday services

The image first-boot services run only when `aurora.imageLayout` is set.
KDE uses Plasma Setup and GNOME uses GNOME Initial Setup to create the owner;
minimal uses the text wizard. `aurora.firstboot=text` selects text setup when
recovering a machine that has no owner. On encrypted image installations, the
first graphical password sign-in also sets the disk password. Once rekeying
succeeds, the factory `owner.nix`
disables `aurora.firstboot.passwordHooks` for the next rebuild. Keyboard settings
come from `services.xserver.xkb`, with an explicit `console.keyMap` taking
precedence for the initrd prompt. Images use mutable accounts, so rebuilds retain
the owner created by the setup wizard.

OpenSSH is available but does not start automatically, and port 22 stays
closed. For temporary access:

```sh
sudo systemctl start sshd
sudo nixos-firewall-tool open tcp 22
```

For persistent access, set `aurora.openssh.startAtBoot = true;` and
`services.openssh.openFirewall = true;`. The temporary firewall change ends
when the firewall reloads.

Vendor firmware and calibration are read from this Mac's EFI partition at
boot into `/run/aurora-firmware`; they are not embedded in the distributable
Nix-store closure. Peripheral admission follows the handoff, and Bluetooth is
admitted by the runtime service before BlueZ. Broadcom radios, the Touch Bar
digitizer and the ALS wait for successful extraction and the real-root firmware
search path. PCI aliases
select the installed Broadcom drivers. ALS calibration remains optional where
the sensor supports operation without it.
Model-specific speaker protection remains enabled.

Steam and FEX use are described in [Gaming](gaming.md). The graphics integration
is enabled by default; Steam and a FEX guest distribution are installed separately.

## Internal modules

These are imported by `default`. Use the options below or standard NixOS
settings; they do not need separate imports. Full option details are in the
[reference](options.md).

| File in `modules/` | Role and configuration |
| --- | --- |
| `ane.nix` | Opt-in Apple Neural Engine (ANE) tools, compiler and `accel` permissions. `aurora.ane.enable` and `firmwarePackage`; Apple firmware must be supplied locally. See [ANE setup](ane.md). |
| `audio.nix` | ALSA restore handling, the early sequencer and PipeWire volume/latency/AirPlay fixes. `aurora.audio.skipLockedControls`, `initrdSequencer` and `pipewireFixes`; all default on. |
| `awdl.nix` | Opt-in AirDrop userspace for supported Broadcom Wi-Fi, excluding the Neo's MediaTek. `aurora.awdl.enable` installs tools without creating `awdl0` or enabling discovery; `createAtBoot` is also off by default. See the option reference for activation commands. |
| `boot-splash.nix` | Desktop Plymouth splash, early display coldplug and quiet GRUB defaults. Configure `boot.plymouth.*` and `boot.loader.*`; minimal has no splash by default. |
| `branding.nix` | Aurora artwork and Plasma's About page. No Aurora-specific options. |
| `camera-denoise.nix` | PipeWire camera filter. `aurora.cameraDenoise.enable`, `package` and `settings`; per-user configuration takes precedence. |
| `dbus.nix` | Removes duplicate service-directory lookups from the system/session bus configuration. No Aurora-specific options. |
| `diag.nix` | Opt-in aurora-diag, the bring-up and regression tool, and `aurora-panic-log`. `aurora.diag.enable` and `package`; off by default. See [aurora-diag](aurora-diag.md). |
| `fex-mesa.nix` | Read-only guest Mesa layer, remounted across switches and rollbacks. `aurora.fexMesa.enable`, `package` and `rootfs`; an absent guest rootfs skips the mount. |
| `fido.nix` | Opt-in Secure Enclave/Touch ID FIDO2/U2F service. `aurora.fido.enable`, `package` and `settings`; requires an enrolled finger. See the option reference for key-storage limits. |
| `firmware.nix` | Initrd/runtime vendor-firmware extraction, peripheral ordering and firmware-search-path restoration after activation. No Aurora-specific options. |
| `firstboot.nix` | Image root preparation/unlock, account handoff and disk rekeying. Activated by `aurora.imageLayout`; `aurora.firstboot.passwordHooks` controls the temporary PAM hooks. |
| `flatpak.nix` | Installs and pins the local Aurora GL extensions for the locked Freedesktop runtimes. `aurora.flatpak.enable` and `package`; it does not add an application repository. |
| `gnome-initial-setup.nix` | GNOME owner-account setup when an image layout is present. `aurora.gnomeInitialSetup.enable`; requires GDM and mutable users. |
| `kbd-light.nix` | Ambient-light keyboard backlight control. `aurora.kbdLight.enable`, `package` and `settings`; the service skips machines without a keyboard backlight. |
| `panel-nits.nix` | Built-in panel brightness shared with the boot loader and macOS through NVRAM `backlight-nits`: the panel starts at the loader's level, and the user's level is stored back (rate limited). `aurora.panelNits.enable` and `package`; machines without the panel backlight or the NVRAM device skip it. |
| `btsync.nix` | Bluetooth pairings made in macOS, copied from NVRAM into BlueZ's storage before bluetoothd starts; keys of devices macOS paired again are refreshed and Linux-only pairings are left alone. `aurora.btsync.enable` and `package`. |
| `parity.nix` | Records payload paths and source identities for finished-image verification. No Aurora-specific options. |
| `plasma-setup.nix` | KDE owner-account setup when an image layout is present. `aurora.plasmaSetup.enable`; requires Plasma Login Manager and mutable users. |
| `platform.nix` | Bluetooth, UPower, regulatory data, speaker protection and model-specific platform rules. No Aurora-specific options. |
| `secure-boot.nix` | Opt-in signed UKIs for the secure boot path. `aurora.secureBoot.enable` writes `/etc/aurora/secboot.conf` and, after every bootloader install, runs `aurora-secboot uki build` for the default generation and the newest `generations` ones (kernel, initrd with its secrets, kernel parameters with `init=` and `lockdown=`), signed with the db key in `keyDir`, which stays out of the Nix store. UKIs of dropped generations are removed. `securePath` (owner keys only) makes the default generation's UKI `EFI/BOOT/BOOTAA64.EFI` and puts GRUB back when turned off. `adoptInstallerKey` (on by default, also without `enable`) moves an owner Stage 2 key the installer left on the ESP into `keyDir` at first boot. |
| `sep.nix` | Touch ID/PAM integration; ordinary login still uses a password. `aurora.sep.greeterFingerprint.enable` adds GNOME greeter authentication. Logind defaults a short power-key press to suspend. The Secure Enclave OpenSSH provider is installed; device access requires explicitly configured `sep-key` group membership. See [Touch ID setup](../sep/README.md). |
| `sep-luks.nix` | Opt-in Secure Enclave LUKS2 unlock. `aurora.sepLuks.enable` and `package` install aurora-sep-cryptenroll (volumes sealed to the Mac), aurora-sep-fde (volumes sealed to users' passwords, with volume owners and a recovery key) and the cryptsetup token plugin; nothing is enrolled until one is run on a volume. `passwordSync` (on with `enable`) runs pam_aurora_sep_fde after pam_unix in `passwd`, so a password change also changes the disk password. `initrd.enable` opens those volumes in the initrd, root included; `initrd.passwordUnlock` loads apple_sep there with `keystore_only=2` for password-sealed volumes. `bootChain` (`audit` by default, or `require`) sets the `boot-chain` line of `fde.conf`, which the initrd also carries. See `docs/luks-sep-owners.md` and `docs/luks-sep-initrd.md` in aurora-sep-userspace. |
| `speaker-upgrade.nix` | `aurora.speakerguardd.upgrade.enable` installs the migration tool and units without starting migration. Enable `aurora.speakerguardd.v2.enable` separately for v2 services, then follow the [preview procedure](speakerguardd-v2-preview.md). |
| `speakerguardd-v2.nix` | Opt-in preview through `aurora.speakerguardd.v2.enable` and `package`. Legacy protection remains installed and gated; v2 takes over only after manual migration and successful checks. Off by default. See the [preview limitations](speakerguardd-v2-preview.md). |
| `steam.nix` | Adapts the standard `programs.steam` module to ARM64 host graphics/audio. Steam is not enabled automatically; x86-only `extest` injection is rejected. |
| `system-fixes.nix` | Malcontent shutdown and persistent NetworkManager dispatcher fixes through `aurora.systemFixes.*`, plus swapfile ordering. |
| `userpages.nix` | The kernel's per-process page-size launcher and `user4k=on`. `aurora.userpages.enable`; an explicit `user4k=off` kernel parameter takes precedence. |
