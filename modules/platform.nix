{ lib, pkgs, ... }:
{
  hardware.bluetooth.enable = true;
  # BlueZ 5.87 includes the empty default-parameter transaction fix.
  assertions = [ {
    assertion = lib.versionAtLeast pkgs.bluez.version "5.87";
    message = "Aurora requires BlueZ >= 5.87 (empty default system config fix).";
  } ];
  hardware.enableRedistributableFirmware = true;
  hardware.firmware = [ pkgs.aurora-avd-firmware ];
  services.upower.enable = true;
  hardware.wirelessRegulatoryDatabase = true;
  systemd.packages = [ pkgs.speakerguardd ];
  services.udev.packages = [ pkgs.speakerguardd ];
  # The sense-PCM udev rule starts the feed-forward guardian only on J700.
  systemd.services.speakersafetyd.serviceConfig = {
    ExecCondition = "${pkgs.speakerguardd}/libexec/speakerguardd/use-feedback-guard";
    # speakersafetyd writes /run/speakersafetyd/speakersafetyd.flag on its
    # first start after boot, and a start that finds it assumes the speakers
    # are at their temperature limit. systemd removes the RuntimeDirectory
    # whenever the unit stops, so every restart within a boot, a crash
    # included, started cold. Leave a root-owned marker in /run when the
    # daemon stops and give a start that finds it the flag back. /run is a
    # tmpfs, so the first start after a reboot stays cold. (Fedora Aurora's
    # 50-aurora-warm-restart.conf.)
    ExecStartPre = "+${pkgs.runtimeShell} -c 'if [ -e /run/speakersafetyd.started ]; then : > /run/speakersafetyd/speakersafetyd.flag; fi'";
    ExecStopPost = "+${pkgs.coreutils}/bin/touch /run/speakersafetyd.started";
  };
  environment.etc."NetworkManager/conf.d/80-aurora-neo-mt7932.conf".source =
    "${pkgs.aurora-neo-platform-config}/lib/NetworkManager/conf.d/80-aurora-neo-mt7932.conf";
  # The MacBook Neo trackpad quirk (it matches only the J700 device tree).
  # libinput reads quirks from its own store path and from this file only,
  # so it goes here; a system that sets its own local overrides wins.
  environment.etc."libinput/local-overrides.quirks".source = lib.mkDefault
    "${pkgs.aurora-neo-platform-config}/share/libinput/60-aurora-neo-j700.quirks";
}
