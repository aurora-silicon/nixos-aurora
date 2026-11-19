# Gaming

Requires the Aurora overlay and module; see [Modules](modules.md). Steam is optional.

## Steam and Aurora Play

```nix
programs.steam.enable = true;
```

The overlay replaces `pkgs.steam` with Aurora's native ARM64 client launcher inside the Steam FHS environment. Its first run downloads Valve's client into the user's home. The module removes the unsupported x86-only 32-bit graphics/audio setup on ARM64. `programs.steam.extest.enable` is unsupported.

The Steam package includes both `steam` and `aurora-play`. Aurora Play lists installed games, launches them through Steam and manages MangoHud settings for discovered native Proton tools. There is no separate Aurora Play package.

## GameMode

Games that Steam starts run under GameMode: while Steam runs, Aurora's `steam` registers every process below a game's reaper (Steam's per-game launcher) with `gamemoded`, so GameMode is active only while a game runs. With Aurora's defaults GameMode keeps the `schedutil` governor and runs the game on the P cores of Macs with at least four ([power profiles](power-profiles.md#games-gamemode)). The KDE and GNOME profiles enable `programs.gamemode`; on `minimal`, set `programs.gamemode.enable = true` to get it. To start games without GameMode, set `AURORA_STEAM_GAMEMODE=0` in Steam's environment, for example `programs.steam.package = pkgs.steam.override { extraEnv.AURORA_STEAM_GAMEMODE = "0"; };`, or turn GameMode off with `programs.gamemode.enable = false;`.

## Native Proton

Steam includes `pkgs.aurora-proton`, also available as `packages.aarch64-linux.proton`. This is pinned ARM64 GE-Proton with Aurora's Wine SME signal-frame fix. Select `Aurora-Proton11-9` in a game's Steam Compatibility settings.

The launcher creates a writable copy under `${XDG_DATA_HOME:-$HOME/.local/share}/aurora-proton/<package-revision>`. Updates retain older copies and user settings. A nonempty `STEAM_EXTRA_COMPAT_TOOLS_PATHS` environment value takes precedence. To disable the bundled tool:

```nix
programs.steam.package = pkgs.steam.override { proton = null; };
```

Source pins, licenses and patch details: [Proton package notes](../pkgs/proton/README.md).

## FEX and page size

`pkgs.fex` uses Aurora's FEX fork. Install its commands explicitly:

```nix
environment.systemPackages = [ pkgs.fex ];
```

Steam automatically enters a 4 KiB process tree; for FEX commands, use:

```sh
userpages 4k FEXBash
```

This requires `aurora.userpages.enable` and a kernel with per-process 4 KiB page support. The rest of the system retains its normal page size.

`aurora.fexMesa` mounts Aurora's x86 Mesa over an owner-supplied distribution rootfs. It does not download that rootfs. Set `aurora.fexMesa.rootfs` to its directory; the default is `/var/lib/aurora/fex/rootfs`. `FEX_ROOTFS` selects the combined provider in login sessions only after it mounts successfully. An existing `FEX_ROOTFS` value is preserved.

Aurora's Flatpak graphics extension is separate and enabled by default. See [the option reference](options.md) for `aurora.fexMesa.*`, `aurora.flatpak.*` and `aurora.userpages.enable`.
