{ config, lib, pkgs, ... }:
{
  # macOS runs the Wi-Fi firmware its system volume ships, so a macOS update
  # brings new Wi-Fi firmware. This follows it: at every boot the installed
  # macOS's Wi-Fi firmware goes to the ESP when it differs, for the next boot.
  options.aurora.wifiFirmware.followMacOS = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = "Keep the ESP's Wi-Fi firmware on the installed macOS's, as macOS does (aurora-wifi-firmware).";
  };
  config = lib.mkIf config.aurora.wifiFirmware.followMacOS {
    environment.systemPackages = [ pkgs.aurora-wifi-firmware ];
    systemd.packages = [ pkgs.aurora-wifi-firmware ];
    systemd.services.aurora-wifi-firmware.wantedBy = [ "multi-user.target" ];
  };
}
