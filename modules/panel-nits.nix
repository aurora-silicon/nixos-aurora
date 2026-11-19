{ config, lib, pkgs, ... }:
let
  cfg = config.aurora.panelNits;
in {
  options.aurora.panelNits = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Share the built-in panel's brightness with the boot loader and macOS
        through the NVRAM backlight-nits variable: the panel starts at the boot
        loader's level instead of a level systemd-backlight saved, and the level
        the user picks is stored back after 5 s without a change, at most once a
        minute and at shutdown. Machines without the panel backlight or the NVRAM
        device skip it. False keeps systemd-backlight's own restore.
      '';
    };
    package = lib.mkPackageOption pkgs "aurora-panel-nits" { };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];
    # The unit, systemd-backlight's drop-in for apple-panel-bl and the udev
    # rule that starts the unit once the backlight and NVRAM device exist.
    systemd.packages = [ cfg.package ];
    services.udev.packages = [ cfg.package ];
  };
}
