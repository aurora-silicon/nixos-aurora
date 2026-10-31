# Bluetooth LE Audio defaults

Aurora supplies LE Audio userspace defaults alongside A2DP and HFP. Fedora and ALARM images
select the independently removable `aurora-bluetooth-le-audio` package. NixOS
imports the equivalent `aurora.bluetooth.leAudio.enable` option (default true).
Neither package is a dependency of the protected platform/audio metapackages.
Installation does not restart Bluetooth, start playback, pair devices, or change
power, discoverability, pairing, codec preference, or automatic connection policy.

The BCM4388 PCIe driver still lacks ISO packet transport: service discovery can
be enabled, but J616s streaming needs a separate driver implementation. See
[the transport limitation](#transport-limitation) before attempting audio use.

## What was missing

The kernel is already sufficient: all three resolved configs have `CONFIG_BT=m`
and `CONFIG_BT_LE=y`. The shared kernel's `net/bluetooth/Makefile` includes
`iso.o` under `CONFIG_BT_LE`; there is no separate `CONFIG_BT_ISO` switch in this
tree. `arch/arm64/configs/asahi.config` supplies the BCM4377/4388 and MT7932 PCIe
transport drivers. The base defconfig and resolved distro configs supply LE.
No kernel config change is needed.

BlueZ's BAP, BASS, VCP and CSIP profiles are experimental at **runtime**. BAP also
checks the ISO socket experimental UUID. A stock, commented-out `Experimental`
and `KernelExperimental` in `main.conf` therefore leaves LE Audio unavailable
even when the controller advertises CIS/ISO capabilities. The defaults enable
experimental D-Bus profiles and **only** ISO sockets, UUID
`6fbaf188-05e0-496a-9885-d6ddfdb4e03e`. They do not enable every kernel experiment.
BlueZ has no `main.conf.d` loader, so Fedora and ALARM use its supported CLI
switches via a service drop-in and an editable environment file; the rest of
`/etc/bluetooth/main.conf` continues to be read.

The distro BlueZ builds already include these plugins. Fedora 44 explicitly
passes `--enable-bap --enable-bass --enable-vcp --enable-csip`; Arch's 5.87
recipe and pinned nixpkgs use the upstream defaults (none of those four features
is disabled). The ALARM recipe inherits Arch packaging; installed binary
qualification remains part of the target checks below. `--enable-experimental`
at configure time concerns experimental **tools** and is distinct from
`Experimental=true` at runtime; nixpkgs does not need a BlueZ rebuild for BAP.

PipeWire supplies the endpoints and the LC3 codec; WirePlumber configures the
BlueZ monitor. Fedora 44 enables `bluez5-codec-lc3` and ships the SPA BlueZ/LC3
plugins in `pipewire-libs`. Arch/ALARM uses `pipewire-audio` with `liblc3`.
Pinned nixpkgs enables BlueZ and LC3 on Linux. The Aurora PipeWire fork already
contains BAP and LC3 support; no fork patch or source-pin replacement is needed.
The upstream PipeWire/WirePlumber defaults already include BAP alongside
classic audio. Aurora does not replace `bluez5.roles` or restrict codecs: a
fixed role list could hide broadcast, hearing-aid or future upstream roles.

## Parity

| Layer | Fedora 44 | ALARM | NixOS (pinned nixpkgs) |
| --- | --- | --- | --- |
| Kernel LE / ISO | Already enabled; no change | Same | Same |
| BlueZ BAP/BASS/VCP/CSIP | Stock BlueZ plugins | Stock BlueZ plugins | Stock BlueZ plugins |
| Runtime BlueZ / ISO | Removable RPM; CLI + editable env file | Removable pacman package; same settings | Native `hardware.bluetooth.settings`, `mkDefault` |
| PipeWire LC3 payload | `pipewire-libs >= 1.2` | `pipewire-audio >= 1.2` | nixpkgs PipeWire, BlueZ/LC3 enabled on Linux |
| WirePlumber BAP roles | Upstream defaults; user configuration preserved | Same | Same; native `wireplumber.extraConfig` for user choices |
| Default selection | All image profiles | All image profiles | All image profiles |
| Opt out | Empty CLI options or remove package | Same | `aurora.bluetooth.leAudio.enable = false;` |
| Apply / rollback | Explicit service restart / remove package | Same | Generation switch / previous generation |

These are stack configuration defaults, not evidence of successful audio streaming.
Controller ISO/CIS advertising is necessary but does not prove that a firmware and
transport combination transfers ISO packets correctly.

## Apply and inspect (lead/operator)

Keep output muted. No pairing or audio playback is needed for these checks.
Restarting Bluetooth can disconnect Bluetooth keyboards and mice; use a local
keyboard or another connection. These commands are for an explicitly authorized
installation, not the read-only investigation.

Fedora:

```sh
sudo dnf install aurora-bluetooth-le-audio
sudo systemctl daemon-reload
sudo systemctl restart bluetooth.service
systemctl --user restart wireplumber.service
bluetoothctl show
```

ALARM (perform a full supported upgrade, avoiding a partial rolling upgrade):

```sh
sudo pacman -Syu aurora-bluetooth-le-audio
sudo systemctl daemon-reload
sudo systemctl restart bluetooth.service
systemctl --user restart wireplumber.service
bluetoothctl show
```

NixOS: update the flake input to the reviewed revision, keep the Aurora module
imported, and leave `aurora.bluetooth.leAudio.enable = true;` (the default), then:

```sh
sudo nixos-rebuild switch
# NixOS deliberately does not restart Bluetooth automatically on config changes.
sudo systemctl restart bluetooth.service
systemctl --user restart wireplumber.service
bluetoothctl show
```

Run WirePlumber as the user whose audio session is being checked. Its normal
upstream session handling still applies. `bluetoothctl show` should now include
Published Audio Capabilities (`00001850-0000-1000-8000-00805f9b34fb`) and Audio
Stream Control (`0000184e-0000-1000-8000-00805f9b34fb`). Related VCS (`1844`),
CSIS (`1846`) and BASS (`184f`) services depend on the enabled profile/role.
There is no single UUID named “BAP” to use as the sole success criterion.

For a controller capability dump, use `btmgmt info` only. Do not run `btmgmt exp`,
`power`, `pair`, `connect`, discovery or any playback as part of this verification.
If services are absent, inspect `systemctl cat bluetooth.service`, the effective
options, `journalctl -b -u bluetooth.service`, and the WirePlumber user journal.
Check for plugin exclusions and errors such as “BAP requires ISO Socket”. The
PipeWire SPA directory must contain `libspa-codec-bluez5-lc3.so` as well as the
BlueZ monitor plugin. LC3plus and HFP LC3-SWB are different codecs.

## User choice and rollback

Fedora/ALARM: set `BLUEZ_LE_AUDIO_OPTIONS=""` in
`/etc/bluetooth/le-audio.conf` to return BlueZ to `main.conf` alone. RPM uses
`%config(noreplace)` and pacman marks this file as `backup`, so upgrades preserve
edits. The kernel feature list supplied on the command line takes precedence
over `KernelExperimental` in `main.conf`; clear the environment option first if
you want to manage that list in `main.conf`. An explicit `Experimental=false` in
`main.conf` can disable the runtime profiles.

To remove the BlueZ defaults, remove just the optional package
(`sudo dnf remove aurora-bluetooth-le-audio` or
`sudo pacman -R aurora-bluetooth-le-audio`), then deliberately reload systemd and
restart Bluetooth and the user's WirePlumber. No platform metapackage removal
is required. Existing `main.conf` settings and pairings remain owned by BlueZ.

A system or user WirePlumber fragment, e.g.
`90-bluetooth-roles.conf`, can replace the roles:

```ini
monitor.bluez.properties = {
  bluez5.roles = [ a2dp_sink a2dp_source hfp_hf hfp_ag ]
}
```

NixOS: set `aurora.bluetooth.leAudio.enable = false;` and rebuild. Alternatively,
ordinary values of `hardware.bluetooth.settings.General.Experimental` and
`KernelExperimental` override the defaults without `mkForce`. WirePlumber role
preferences remain entirely in the user's native `wireplumber.extraConfig` or
user configuration. Other modules or user fragments may
still enable LE Audio; opting out removes only Aurora's defaults. Roll back with
`sudo nixos-rebuild switch --rollback` and explicitly restart Bluetooth if its
configuration changed.

Broadcast audio is available as an additional user choice: add `bap_bcast_sink`
and/or `bap_bcast_source` to a complete roles list using PipeWire/WirePlumber's
native configuration. No broadcast is started by these defaults.

## Public implementation sources

- [Shared kernel Bluetooth build rules](https://github.com/aurora-silicon/linux/blob/5d7c3e74019d0a04a22e0c6e5cec5a297e245fd6/net/bluetooth/Makefile),
  [Kconfig](https://github.com/aurora-silicon/linux/blob/5d7c3e74019d0a04a22e0c6e5cec5a297e245fd6/net/bluetooth/Kconfig),
  [universal fragment](https://github.com/aurora-silicon/linux/blob/5d7c3e74019d0a04a22e0c6e5cec5a297e245fd6/arch/arm64/configs/asahi.config).
- [BlueZ 5.87 configure](https://github.com/bluez/bluez/blob/5.87/configure.ac),
  [BAP](https://github.com/bluez/bluez/blob/5.87/profiles/audio/bap.c),
  [main.conf](https://github.com/bluez/bluez/blob/5.87/src/main.conf),
  [configuration and CLI parser](https://github.com/bluez/bluez/blob/5.87/src/main.c).
- [Fedora 44 BlueZ](https://src.fedoraproject.org/rpms/bluez/blob/f44/f/bluez.spec)
  and [PipeWire](https://src.fedoraproject.org/rpms/pipewire/blob/f44/f/pipewire.spec).
- [Arch BlueZ](https://gitlab.archlinux.org/archlinux/packaging/packages/bluez/-/blob/main/PKGBUILD)
  and [PipeWire](https://gitlab.archlinux.org/archlinux/packaging/packages/pipewire/-/blob/main/PKGBUILD).
- [Pinned nixpkgs BlueZ](https://github.com/NixOS/nixpkgs/blob/e7439b6b14ad3cc35d05608ebca9bce01a25f5f8/pkgs/by-name/bl/bluez/package.nix),
  [PipeWire](https://github.com/NixOS/nixpkgs/blob/e7439b6b14ad3cc35d05608ebca9bce01a25f5f8/pkgs/by-name/pi/pipewire/package.nix).
- [Aurora PipeWire LC3 build](https://github.com/aurora-silicon/pipewire/blob/5009ec694a0a6ec6351eac787769a128b6a168e1/spa/plugins/bluez5/meson.build),
  [WirePlumber Bluetooth configuration](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/bluetooth.html).

## Transport limitation

The BCM4388 controller advertises ISO/CIS capabilities, but the shared public
`hci_bcm4377` PCIe driver at the packaged kernel pin and at `aurora-wip` still
handles only HCI command, ACL and SCO packets in `bcm4377_hci_send_frame`.
`HCI_ISODATA_PKT` reaches the default `-EILSEQ` rejection, and there is no
corresponding ISO receive ring dispatch. Enabling BlueZ services does **not**
fix this transport gap. J616s LE Audio streaming remains unimplemented in this
driver and needs a separate licensed-public-source transport implementation
and later, explicitly authorized qualification.

The public MT7932 PCIe driver has ISO TX/RX rings (9/10) and ISO packet framing.
This is source evidence only; controller-advertised roles and actual ISO transfer
remain separate checks. No playback or pairing was performed for this change.

Sources: [BCM send callback](https://github.com/aurora-silicon/linux/blob/5d7c3e74019d0a04a22e0c6e5cec5a297e245fd6/drivers/bluetooth/hci_bcm4377.c#L1986),
[MT7932 transport](https://github.com/aurora-silicon/linux/blob/5d7c3e74019d0a04a22e0c6e5cec5a297e245fd6/drivers/bluetooth/mt7932_bt_pcie.c).
