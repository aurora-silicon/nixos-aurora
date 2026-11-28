{ config, lib, pkgs, ... }:
let
  cfg = config.aurora.wifisync;
in {
  options.aurora.wifisync = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = config.networking.networkmanager.enable;
      defaultText = lib.literalExpression "config.networking.networkmanager.enable";
      description = ''
        Use the Wi-Fi networks saved in macOS: when the NVRAM device appears,
        aurora-wifisync adds them to NetworkManager as keyfiles before
        NetworkManager starts, so a first boot joins a network macOS knows.
        Profiles made on Linux are left alone and no key is printed. False
        leaves NetworkManager's profiles alone.
      '';
    };
    package = lib.mkPackageOption pkgs "aurora-wifisync" { };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];
    # The unit and the udev rule that starts it once the NVRAM device exists.
    systemd.packages = [ cfg.package ];
    services.udev.packages = [ cfg.package ];
  };
}
