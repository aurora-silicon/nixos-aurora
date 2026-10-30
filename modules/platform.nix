{ lib, pkgs, ... }:
{
  hardware.bluetooth.enable = true;
  hardware.enableRedistributableFirmware = true;
  hardware.firmware = [ pkgs.aurora-avd-firmware ];
  services.upower.enable = true;
  hardware.wirelessRegulatoryDatabase = true;
  systemd.packages = [ pkgs.speakerguardd ];
  services.udev.packages = [ pkgs.speakerguardd ];
  # The sense-PCM udev rule starts the feed-forward guardian only on J700.
  systemd.services.speakersafetyd.serviceConfig.ExecCondition =
    "${pkgs.speakerguardd}/libexec/speakerguardd/use-feedback-guard";
  environment.etc."NetworkManager/conf.d/80-aurora-neo-mt7932.conf".source =
    "${pkgs.aurora-neo-platform-config}/lib/NetworkManager/conf.d/80-aurora-neo-mt7932.conf";
  # The MacBook Neo trackpad quirk (it matches only the J700 device tree).
  # libinput reads quirks from its own store path and from this file only,
  # so it goes here; a system that sets its own local overrides wins.
  environment.etc."libinput/local-overrides.quirks".source = lib.mkDefault
    "${pkgs.aurora-neo-platform-config}/share/libinput/60-aurora-neo-j700.quirks";
}
