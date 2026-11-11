{ config, lib, pkgs, ... }:
let
  cfg = config.aurora.btsync;
in {
  options.aurora.btsync = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Use the Bluetooth pairings made in macOS: when the NVRAM device appears,
        aurora-btsync copies them into BlueZ's storage before bluetoothd starts
        and refreshes the keys of devices macOS paired again. Pairings made only
        on Linux are left alone. False leaves BlueZ's storage to bluetoothd.
      '';
    };
    package = lib.mkPackageOption pkgs "aurora-btsync" { };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];
    # The unit (with its asahi-btsync.service alias) and the udev rule that
    # starts it once the NVRAM device exists.
    systemd.packages = [ cfg.package ];
    services.udev.packages = [ cfg.package ];
  };
}
