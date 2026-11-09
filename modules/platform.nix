{ lib, pkgs, ... }:
{
  hardware.bluetooth.enable = true;
  # BlueZ 5.87 includes the empty default-parameter transaction fix.
  assertions = [ {
    assertion = lib.versionAtLeast pkgs.bluez.version "5.87";
    message = "Aurora requires BlueZ >= 5.87 (empty default system config fix).";
  } ];
  # The Touch Bar of the 13-inch M1 and M2 MacBook Pros (J293, J493), as Fedora
  # (aurora-platform requires tiny-dfr) and ALARM (in every image) ship it.
  # tiny-dfr's udev rule starts it only when a Touch Bar display appears, so
  # it stays inert on every other Mac.
  hardware.apple.touchBar.enable = lib.mkDefault true;
  hardware.enableRedistributableFirmware = true;
  hardware.firmware = [ pkgs.aurora-avd-firmware ];
  services.upower.enable = true;
  hardware.wirelessRegulatoryDatabase = true;
  systemd.packages = [ pkgs.speakerguardd ];
  # Speakers on speakerguardd v2: v2 installs beside the legacy
  # daemons behind its gate, and aurora-speaker-upgrade switches a Mac at boot
  # only when its own tuning passes the silent self-check. A refused Mac keeps
  # speakersafetyd. Both stay user options (set them to false to opt out).
  aurora.speakerguardd.v2.enable = lib.mkDefault true;
  aurora.speakerguardd.upgrade.enable = lib.mkDefault true;
  services.udev.packages = [
    pkgs.speakerguardd
    # Keep the firmware's product name unchanged in ID_MODEL (hostnamed's
    # hardware model): udev turns parentheses into underscores in $attr{}.
    (pkgs.writeTextFile {
      name = "aurora-dmi-id-rules";
      destination = "/lib/udev/rules.d/61-aurora-dmi-id.rules";
      text = builtins.replaceStrings [ "@sed@" ] [ "${pkgs.gnused}/bin/sed" ]
        (builtins.readFile ./61-aurora-dmi-id.rules);
    })
    # Name the DMI vendor "Apple" instead of "Apple Inc." for hostnamed.
    (pkgs.writeTextFile {
      name = "aurora-dmi-vendor-hwdb";
      destination = "/lib/udev/hwdb.d/60-aurora-dmi-vendor.hwdb";
      text = builtins.readFile ./60-aurora-dmi-vendor.hwdb;
    })
    # The GPU card only renders (the display is the apple-drm card): tag it
    # mutter-device-ignore so mutter stops failing to open it at every login.
    (pkgs.writeTextFile {
      name = "aurora-gpu-render-only-rules";
      destination = "/lib/udev/rules.d/62-aurora-gpu-render-only.rules";
      text = builtins.readFile ./62-aurora-gpu-render-only.rules;
    })
  ];
  # The sense-PCM udev rule starts the feed-forward guardian only on J700.
  systemd.services.speakersafetyd.serviceConfig = {
    # Preserve the board-specific legacy daemon selector.
    ExecCondition = [ "${pkgs.speakerguardd}/libexec/speakerguardd/use-feedback-guard" ];
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
