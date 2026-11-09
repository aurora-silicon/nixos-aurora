# Aurora options

Generated from the module declarations. See [Modules](https://github.com/aurora-silicon/nixos-aurora/blob/main/docs/modules.md)
for imports and behavior, and [Documentation](https://github.com/aurora-silicon/nixos-aurora/blob/main/docs/documentation.md) to regenerate this reference.

This lists every public `aurora.*` option, including submodule fields. Standard NixOS and
Apple Silicon options remain available; see the links in the module guide. For daemon settings,
`null` preserves the program's default. Required fields apply only when their parent is configured.

## `aurora.ane.enable`

Install the Apple Neural Engine (ANE) tools and compiler, create the `accel` group and add
device access rules. Disabling this omits that userspace integration;
it does not change the kernel driver or fetch firmware.

**Type:** boolean

**Default:** `false`

**Example:** `true`

**Declared in:** [ane.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/ane.nix)

## `aurora.ane.firmwarePackage`

Optional owner-supplied firmware package with uncompressed files under
`lib/firmware/apple/ane`. Used only when `aurora.ane.enable` is true;
null adds no firmware. Fetch locally with `omarchy-ane-firmware-fetch`;
no Apple firmware is included or fetched by a build.

**Type:** null or package

**Default:** `null`

**Declared in:** [ane.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/ane.nix)

## `aurora.audio.initrdSequencer`

Add `snd-seq` to the modules available in the initrd for early display
audio. This includes the module without forcing an early load; false
omits Aurora's additional entry.

**Type:** boolean

**Default:** `true`

**Declared in:** [audio.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/audio.nix)

## `aurora.audio.pipewireFixes`

Run the PipeWire daemon from aurora-pipewire, nixpkgs' PipeWire with
the filter-graph volume and latency fixes and the AirPlay sender fixes
that Fedora and Arch Linux ARM carry. Without it, an update that repeats
the current volume or mute state applies the speaker volume twice.

**Type:** boolean

**Default:** `true`

**Declared in:** [audio.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/audio.nix)

## `aurora.audio.skipLockedControls`

Select and install Aurora's ALSA utilities, whose restore skips controls
locked by another process. False leaves ALSA utility selection unchanged.

**Type:** boolean

**Default:** `true`

**Declared in:** [audio.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/audio.nix)

## `aurora.awdl.createAtBoot`

Create awdl0 at boot (awdl0.service), idle until a window opens.

**Type:** boolean

**Default:** `false`

**Declared in:** [awdl.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/awdl.nix)

## `aurora.awdl.enable`

Install the userspace for AirDrop over AWDL, the Wi-Fi link AirDrop
runs over, on Macs with Broadcom Wi-Fi (BCM4378, BCM4387, BCM4388;
not the Neo's MediaTek). The firmware implements AWDL and the kernel's
brcmfmac exposes it as awdl0. Enabling this installs the tools, the
airdrop-receiver user unit and the sleep hook, and keeps awdl0 out of
NetworkManager. It does not create awdl0 or make the Mac
discoverable: run `sudo awdl-up`, then
`pkexec omdrop-discoverable start 600` for a ten-minute window, and
`systemctl --user start airdrop-receiver` to receive. See
share/doc/omdrop-awdl/README.md. Off by default.

**Type:** boolean

**Default:** `false`

**Declared in:** [awdl.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/awdl.nix)

## `aurora.awdl.package`

The omdrop-awdl package to use.

**Type:** package

**Default:** `pkgs.omdrop-awdl`

**Declared in:** [awdl.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/awdl.nix)

## `aurora.cameraDenoise.enable`

Start the denoise filter with each user's PipeWire service and enable
PipeWire by default. It publishes filtered camera nodes while retaining
the originals. False omits this integration, its settings and its
default PipeWire enablement; PipeWire then follows other configuration.

CPU filtering is built in. Additional backends must be installed in
the selected package's `lib/aurora-camera-denoise` directory.

**Type:** boolean

**Default:** `true`

**Declared in:** [camera-denoise.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/camera-denoise.nix)

## `aurora.cameraDenoise.package`

The aurora-camera-denoise package to use.

**Type:** package

**Default:** `pkgs.aurora-camera-denoise`

**Declared in:** [camera-denoise.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/camera-denoise.nix)

## `aurora.cameraDenoise.settings`

Values for `[denoise]` in `/etc/aurora-camera-denoise/denoise.conf`;
an empty set writes no file. Nix validates value types, not freeform
key names or numeric ranges. Unknown keys fail daemon configuration;
some numeric values are normalized instead of rejected.

Gain/noise thresholds (`enter-gain`, `exit-gain`, `enter-noise`,
`exit-noise`) override board data. Use nonnegative integer gains and
frame counts. Zero `enter-gain` disables its trigger; nonpositive
`enter-noise` disables the noise trigger. Exit thresholds are capped
at their entry thresholds. `fps-threshold` defaults to 30; nonpositive
values remove the frame-rate gate. `ramp-up-frames` and
`ramp-down-frames` default to 0 and 30; zero makes transitions immediate.

Other keys are `low-light-frame-rate` (`on` by default, permits longer
exposures and lower frame rates), `prefer` (preferred plugin names,
comma-separated; default `ane`) and `drivers` (camera driver names,
comma-separated; default `apple-isp`). Strings, integers and floats are
accepted as freeform values; use `"on"` or `"off"` for switch keys.
These values override board data; each user's
`~/.config/aurora-camera-denoise/denoise.conf` wins over this file.
Running services pick up a change with
`systemctl --user reload aurora-camera-denoise`.

**Type:** open submodule of attribute set of (string or signed integer or floating point number)

**Default:** `{ }`

**Example:**

```nix
{
  enter-gain = 1536;
  exit-gain = 1280;
  mode = "auto";
}
```

**Declared in:** [camera-denoise.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/camera-denoise.nix)

## `aurora.cameraDenoise.settings.backend`

`auto` tries preferred installed plugins. With temporal filtering
on, the CPU temporal filter remains when no plugin is usable;
`cpu` selects that filter alone. With temporal filtering off,
`auto` falls back to the CPU as the sole backend. Null keeps `auto`.

**Type:** null or string

**Default:** `null`

**Declared in:** [camera-denoise.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/camera-denoise.nix)

## `aurora.cameraDenoise.settings.mode`

Trigger mode: `auto` follows gain/noise thresholds, `on` forces
filtering, and `off` passes frames through. Temporal filtering
is controlled separately. Null leaves the package default (`auto`).

**Type:** null or one of "auto", "on", "off"

**Default:** `null`

**Declared in:** [camera-denoise.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/camera-denoise.nix)

## `aurora.cameraDenoise.settings.temporal`

`on` runs the temporal filter on every frame unless mode is `off`;
`off` gates the selected backend with the trigger. Null leaves
the package default (`on`).

**Type:** null or one of "on", "off"

**Default:** `null`

**Declared in:** [camera-denoise.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/camera-denoise.nix)

## `aurora.cameraDenoise.settings.threads`

CPU worker count; 0 uses one worker. Null leaves the package default (0).

**Type:** null or (unsigned integer, meaning >=0)

**Default:** `null`

**Declared in:** [camera-denoise.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/camera-denoise.nix)

## `aurora.desktop`

Desktop profile: KDE with Plasma Login Manager, GNOME with GDM, or
`minimal` without a desktop or greeter. Shared hardware services remain
enabled in all three profiles.

**Type:** one of "kde", "gnome", "minimal"

**Default:** `"kde"`

**Declared in:** [aurora.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/aurora.nix)

## `aurora.fexMesa.enable`

Mount x86_64 and i686 Aurora Mesa over the guest rootfs at
`/var/lib/aurora/fex/mesa-rootfs`. Set `FEX_ROOTFS` only when the provider
is mounted and the user has not set it. False removes this integration
and unmounts the provider on a switch; guest distribution files remain.

**Type:** boolean

**Default:** `true`

**Declared in:** [fex-mesa.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/fex-mesa.nix)

## `aurora.fexMesa.package`

The aurora-fex-mesa package to use.

**Type:** package

**Default:** `pkgs.aurora-fex-mesa`

**Declared in:** [fex-mesa.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/fex-mesa.nix)

## `aurora.fexMesa.rootfs`

Absolute path to an unpacked FEX guest distribution containing `usr`.
It is neither downloaded nor modified; the service skips a missing
`usr` directory. Colons, commas, backslashes and newlines are unsupported
because this path is an overlay mount's lower layer.

**Type:** string

**Default:** `"/var/lib/aurora/fex/rootfs"`

**Example:** `"/srv/fex/Fedora"`

**Declared in:** [fex-mesa.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/fex-mesa.nix)

## `aurora.fido.enable`

Run aurora-fidod, which makes this Mac's Secure Enclave and Touch ID a
FIDO2/U2F security key: WebAuthn and passkeys in browsers, SSH
ecdsa-sk keys, pam_u2f and systemd-cryptenroll --fido2-device. Every
operation asks for a Touch ID match. Keys live in the Secure Enclave
when the kernel has /dev/sep-key and are sealed by it otherwise (root
on this Mac can copy sealed keys); `aurora-fido status` says which.
Off by default. Needs Touch ID (fprintd with an enrolled finger).

**Type:** boolean

**Default:** `false`

**Declared in:** [fido.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/fido.nix)

## `aurora.fido.package`

The aurora-fido package to use.

**Type:** package

**Default:** `pkgs.aurora-fido`

**Declared in:** [fido.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/fido.nix)

## `aurora.fido.settings`

/etc/aurora-fido/aurora-fido.conf, by section ([touchid],
[authenticator], [keys]). Unset keys keep the daemon's defaults; see
docs/fido.md in aurora-sep-userspace. touchid.policy picks who may
approve new credentials, as on macOS: "touchid-or-password" (default:
Touch ID, or your password in the polkit dialog), "touchid-any" or
"touchid-current" (Touch ID only; the latter retires a credential
when the enrolled fingers change).

**Type:** attribute set of attribute set of (string or signed integer or boolean)

**Default:** `{ }`

**Example:**

```nix
{
  keys = {
    store = "sep-key";
  };
  touchid = {
    policy = "touchid-current";
  };
}
```

**Declared in:** [fido.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/fido.nix)

## `aurora.firstboot.passwordHooks`

Declare PAM hooks that make the owner's first password sign-in unlock
the encrypted disk. Used only with `aurora.imageLayout`. After rekeying,
the hooks become inert and the generated `owner.nix` disables them for
the next rebuild; hand-edited files receive instructions in the journal.
False omits these hooks, not the rest of first-boot setup.

**Type:** boolean

**Default:** `true`

**Declared in:** [firstboot.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/firstboot.nix)

## `aurora.flatpak.enable`

Enable Flatpak and install pinned Aurora GL runtime extensions before
desktop login. Supply GL driver defaults without replacing an explicit
`FLATPAK_GL_DRIVERS`. False removes Aurora's managed extensions and
overrides on a switch; Flatpak itself follows its other configuration.

**Type:** boolean

**Default:** `true`

**Declared in:** [flatpak.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/flatpak.nix)

## `aurora.flatpak.package`

The aurora-flatpak-gl package to use.

**Type:** package

**Default:** `pkgs.aurora-flatpak-gl`

**Declared in:** [flatpak.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/flatpak.nix)

## `aurora.gnomeInitialSetup.enable`

Create the first owner account with GNOME Initial Setup.
Requires GDM and mutable users. False omits Aurora's setup
integration without disabling GNOME or removing existing accounts.

**Type:** boolean

**Default:** `config.aurora.desktop == "gnome" && config.aurora.imageLayout != null`

**Declared in:** [gnome-initial-setup.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/gnome-initial-setup.nix)

## `aurora.imageLayout`

Filesystem identities of an Aurora installer layout. Non-null enables
its root-unlock, first-boot and GRUB filesystem-lookup adapters and selects
these devices for `/`, `/home`, `/boot` and `/boot/efi`. Identities must
match an installer-prepared layout; this does not create that layout.
Null omits those adapters. The image module
supplies profile defaults; generated `machine.nix` preserves installed
identities.

**Type:** null or (submodule)

**Default:** `null`

**Declared in:** [firstboot.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/firstboot.nix)

## `aurora.imageLayout.bootUUID`

Lowercase ext4 filesystem UUID for the separate `/boot` filesystem.

**Type:** string matching the pattern [a-f0-9-]{36}

**Default:** required.

**Example:** `"3429647d-29a2-411c-8924-2545fda1ec34"`

**Declared in:** [firstboot.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/firstboot.nix)

## `aurora.imageLayout.efiUUID`

FAT filesystem UUID for `/boot/efi`, in `XXXX-XXXX` form; not its GPT PARTUUID.

**Type:** string matching the pattern [A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}

**Default:** required.

**Example:** `"1E08-14ED"`

**Declared in:** [firstboot.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/firstboot.nix)

## `aurora.imageLayout.rootUUID`

Lowercase Btrfs filesystem UUID shared by the `root` and `home`
subvolumes. Use the filesystem UUID, not the GPT partition or LUKS UUID.

**Type:** string matching the pattern [a-f0-9-]{36}

**Default:** required.

**Example:** `"eb688499-cc41-4c4c-b00b-dbf33e05427c"`

**Declared in:** [firstboot.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/firstboot.nix)

## `aurora.kbdLight.enable`

Start the keyboard-backlight service at boot. It follows ambient light,
turns off with the lid closed or displays asleep, and respects manual
desktop adjustments. Without a keyboard backlight the service is skipped.
False removes the service integration and its environment settings.

**Type:** boolean

**Default:** `true`

**Declared in:** [kbd-light.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/kbd-light.nix)

## `aurora.kbdLight.package`

The aurora-kbd-light package to use.

**Type:** package

**Default:** `pkgs.aurora-kbd-light`

**Declared in:** [kbd-light.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/kbd-light.nix)

## `aurora.kbdLight.settings`

Overrides passed through the service environment; null fields leave
package defaults. Use nonnegative numbers and
`0 < fullLux < onLux <= offLux`; the daemon enforces this ordering,
not the Nix option types. Percentage fractions are truncated by
the daemon. Its optional `/etc/default/aurora-kbd-light` environment
file remains supported and takes precedence over these values.

**Type:** submodule

**Default:** `{ }`

**Example:**

```nix
{
  maxPercent = 70;
}
```

**Declared in:** [kbd-light.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/kbd-light.nix)

## `aurora.kbdLight.settings.fullLux`

Lux at or below which the maximum level is used; positive and below onLux. The default package uses 2. Null leaves the selected package's default.

**Type:** null or unsigned integer, meaning >=0, or floating point number

**Default:** `null`

**Declared in:** [kbd-light.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/kbd-light.nix)

## `aurora.kbdLight.settings.maxPercent`

Automatic level in darkness, capped at 100 percent by the daemon. The default package uses 50. Null leaves the selected package's default.

**Type:** null or unsigned integer, meaning >=0, or floating point number

**Default:** `null`

**Declared in:** [kbd-light.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/kbd-light.nix)

## `aurora.kbdLight.settings.minPercent`

Initial automatic level in percent; the daemon limits it to maxPercent. The default package uses 10. Null leaves the selected package's default.

**Type:** null or unsigned integer, meaning >=0, or floating point number

**Default:** `null`

**Declared in:** [kbd-light.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/kbd-light.nix)

## `aurora.kbdLight.settings.offLux`

Lux above which the backlight turns off; at least onLux. The default package uses 120. Null leaves the selected package's default.

**Type:** null or unsigned integer, meaning >=0, or floating point number

**Default:** `null`

**Declared in:** [kbd-light.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/kbd-light.nix)

## `aurora.kbdLight.settings.onLux`

Lux below which the backlight turns on; above fullLux and at most offLux. The default package uses 60. Null leaves the selected package's default.

**Type:** null or unsigned integer, meaning >=0, or floating point number

**Default:** `null`

**Declared in:** [kbd-light.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/kbd-light.nix)

## `aurora.openssh.startAtBoot`

Start the OpenSSH server and generate its host keys at boot. When false,
manual or socket activation remains available. This does not open port
22; configure `services.openssh.openFirewall` separately.

**Type:** boolean

**Default:** `false`

**Declared in:** [aurora.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/aurora.nix)

## `aurora.plasmaSetup.enable`

Create the first owner account with Plasma Setup.
Requires Plasma Login Manager and mutable users. False omits this setup
integration without disabling KDE or removing existing accounts.

**Type:** boolean

**Default:** `config.aurora.desktop == "kde" && config.aurora.imageLayout != null`

**Declared in:** [plasma-setup.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/plasma-setup.nix)

## `aurora.sep.greeterFingerprint.enable`

Patch GNOME Shell's greeter to offer fingerprint sign-in as well as
lock-screen authentication. The greeter waits for Touch ID readiness,
up to 90 seconds after boot; fingerprint sign-in does not unlock the
keyring. False leaves the normal password greeter and keeps lock-screen,
sudo and polkit fingerprint authentication enabled.

**Type:** boolean

**Default:** `false`

**Declared in:** [sep.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/sep.nix)

## `aurora.sep.requirePasswordAfterBoot`

Touch ID after a restart. On (the default): as on macOS, the first login
or unlock after boot needs the password ("Your password is required to
enable Touch ID."), and Touch ID works after that password. Off: Touch ID
works from the first login after boot. Written
to /etc/aurora/touchid.conf (require_password_after_boot) and applied
by aurora-touchid-boot.service at every boot.

**Type:** boolean

**Default:** `true`

**Declared in:** [sep.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/sep.nix)

## `aurora.speakerguardd.upgrade.enable`

Install aurora-speaker-upgrade (the legacy-to-speakerguardd-v2 upgrade tool); it never runs by itself. speakerguardd v2 is a preview. It does not fully match macOS yet. The legacy protection (speakersafetyd, speakerguardd 0.1) is the supported default and stays installed. To go back at any time: sudo aurora-speaker-upgrade --revert.

**Type:** boolean

**Default:** `false`

**Declared in:** [speaker-upgrade.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/speaker-upgrade.nix)

## `aurora.speakerguardd.v2.enable`

Install speakerguardd 1.0 (preview) beside the 0.1 speakerguardd and
speakersafetyd, with its gate on both stacks. Nothing changes for the
speakers by itself: the gate keeps speakersafetyd in charge until
aurora-speaker-upgrade (aurora.speakerguardd.upgrade.enable) has
verified this Mac's own tuning and switched the dual-interface
kernel to v2's lease. Off by default.

**Type:** boolean

**Default:** `false`

**Declared in:** [speakerguardd-v2.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/speakerguardd-v2.nix)

## `aurora.speakerguardd.v2.package`

The speakerguardd-v2 package to use.

**Type:** package

**Default:** `pkgs.speakerguardd-v2`

**Declared in:** [speakerguardd-v2.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/speakerguardd-v2.nix)

## `aurora.stage2.enable`

Refresh the checked ESP Stage 2 on bootloader installs and commit trials
on compatible aura versions. Monitor-free aura uses a board-specific
CTXR image on Macs booting Mach-O Stage 1. False disables automatic
installs, DT ABI pre-switch checks and trial commit/guard units, including
the upstream unchecked copy. Update commands remain installed; Stage 1
is never written by this module.

**Type:** boolean

**Default:** `true`

**Declared in:** [installed.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/installed.nix)

## `aurora.stage2.requiredBoards`

Board identifiers whose device trees must be present in the shared
Stage 2; omit the `apple,` prefix. A missing board fails its build.
This validates contents, not which boards are included by the kernel.

**Type:** list of string

**Default:**

```nix
[
  "j700"
  "j616s"
  "j614s"
]
```

**Example:**

```nix
[
  "j700"
  "j616s"
  "j614s"
]
```

**Declared in:** [installed.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/installed.nix)

## `aurora.systemFixes.malcontentSignal`

Add the signal-handling and exit-status drop-ins for malcontent's optional
daemons. This does not start or install absent daemons; false omits the
drop-ins and retains their packaged behavior.

**Type:** boolean

**Default:** `true`

**Declared in:** [system-fixes.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/system-fixes.nix)

## `aurora.systemFixes.nmDispatcherPersist`

Run NetworkManager's dispatcher with `--persist` and stop it after
NetworkManager, avoiding failed event activation during shutdown. Used
only when NetworkManager is enabled; false retains its packaged lifecycle.

**Type:** boolean

**Default:** `true`

**Declared in:** [system-fixes.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/system-fixes.nix)

## `aurora.systemFixes.nmKeepWakeOnLan`

Keep a Wake-on-LAN/WLAN device that is still activated after wake instead of reconnecting it.

**Type:** boolean

**Default:** `true`

**Declared in:** [system-fixes.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/system-fixes.nix)

## `aurora.systemFixes.wakeForNetwork`

Wake for network access (magic packet on wired interfaces that support
it and on Wi-Fi phys with magic-packet WoWLAN). The default follows the
power adapter, as macOS laptops do: armed on AC, disarmed on battery.

**Type:** one of "power-adapter", "always", "never"

**Default:** `"power-adapter"`

**Declared in:** [system-fixes.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/system-fixes.nix)

## `aurora.update.flake`

Consumer flake updated by `aurora-update`, optionally followed by its
NixOS configuration name. Without a selector the host name is used.
Set this for systems maintained with direct `nixos-rebuild` commands:
NixOS does not retain their original consumer flake reference.
An explicit `aurora-update --flake` overrides this and remembers a
successful local activation only for that exact system generation.
Factory images fall back to `/etc/nixos#aurora`; other systems require
this option or an explicit reference. Updating requires a writable
local consumer lockfile.

**Type:** null or string

**Default:** `null`

**Example:** `"/home/owner/nixos#macbook"`

**Declared in:** [installed.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/installed.nix)

## `aurora.update.inputName`

Name of the Aurora input to update in the consumer flake.

**Type:** string

**Default:** `"aurora"`

**Declared in:** [installed.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/installed.nix)

## `aurora.userpages.enable`

Add `user4k=on` first on the kernel command line and install the
`userpages` launcher (`userpages 4k COMMAND`). False omits both.
`boot.kernelParams = [ "user4k=off" ];` overrides the boot selection
while retaining the launcher. Kernel-command-line changes need a reboot.

**Type:** boolean

**Default:** `true`

**Declared in:** [userpages.nix](https://github.com/aurora-silicon/nixos-aurora/blob/main/modules/userpages.nix)
