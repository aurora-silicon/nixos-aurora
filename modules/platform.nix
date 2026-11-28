{ config, lib, pkgs, ... }:
let
  avdFirmware = pkgs.aurora-avd-firmware;
  # The oldest avd-fw the booted kernel's device trees work with (pkgs/kernel.nix).
  minAvdFirmware = config.boot.kernelPackages.kernel.auroraMinAvdFirmware or null;
  # /dev/accel (the Neural Engine) for the accel group and the local
  # session user, instead of systemd's mode 0666; with or without
  # aurora.ane. Same rule as Fedora's aurora-platform-core and ALARM's
  # aurora-system-fixes.
  accelRules = pkgs.writeTextFile {
    name = "aurora-accel-rules";
    destination = "/lib/udev/rules.d/70-aurora-accel.rules";
    text = builtins.readFile ./70-aurora-accel.rules;
  };
  udevadm = "${config.systemd.package}/bin/udevadm";
in {
  hardware.bluetooth.enable = true;
  # BlueZ 5.87 includes the empty default-parameter transaction fix.
  assertions = [ {
    assertion = lib.versionAtLeast pkgs.bluez.version "5.87";
    message = "Aurora requires BlueZ >= 5.87 (empty default system config fix).";
  } {
    assertion = minAvdFirmware == null || lib.versionAtLeast avdFirmware.version minAvdFirmware;
    message = "This kernel needs aurora-avd-firmware ${toString minAvdFirmware} or later, "
      + "whose v4 image fits the T8122 CM3 SRAM window at +0x90000 (linux#2586); "
      + "with ${avdFirmware.version} the M3 video decoder fails to probe.";
  } ];
  # The Touch Bar of the 13-inch M1 and M2 MacBook Pros (J293, J493), as Fedora
  # (aurora-platform requires tiny-dfr) and ALARM (in every image) ship it.
  # tiny-dfr's udev rule starts it only when a Touch Bar display appears, so
  # it stays inert on every other Mac.
  hardware.apple.touchBar.enable = lib.mkDefault true;
  hardware.enableRedistributableFirmware = true;
  hardware.firmware = [ avdFirmware ];
  services.upower.enable = true;
  hardware.wirelessRegulatoryDatabase = true;
  # speakerguardd v2 is the only speaker stack and the only program that takes
  # the kernel's speaker interlock. aurora-speaker-upgrade moves a Mac to it at
  # boot when its own tuning passes the silent self-check; a refused Mac keeps
  # its speakers at the kernel's floor. Both are on with the platform, as the
  # Fedora and ALARM packages require them; only lib.mkForce false turns one
  # off, which leaves the speakers at that floor (there is no other stack).
  aurora.speakerguardd.v2.enable = true;
  aurora.speakerguardd.upgrade.enable = true;
  # speakersafetyd never runs: nixos-apple-silicon's sound module adds its unit
  # (overlay.nix ships it empty), and this masks speakersafetyd.service.
  systemd.services.speakersafetyd.enable = lib.mkForce false;
  services.udev.packages = [
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
    # Trackpad clicks from the host, as macOS does, where the MTP trackpad
    # has a haptic actuator (hid_magicmouse haptic_press).
    (pkgs.writeTextFile {
      name = "aurora-trackpad-clicks-rules";
      destination = "/lib/udev/rules.d/64-aurora-trackpad-clicks.rules";
      text = builtins.readFile ./64-aurora-trackpad-clicks.rules;
    })
    accelRules
  ];
  users.groups.accel = { };
  # A switch gives an existing /dev/accel node the rule's group and mode, not
  # only the next boot: NixOS restarts udevd when the rules change but replays
  # no events, and only an add event reapplies GROUP and MODE (a change event
  # does not). Fedora (%posttrans) and ALARM (a pacman hook) do the same.
  systemd.services.aurora-accel-permissions = {
    description = "Apply the /dev/accel permissions to existing nodes";
    wantedBy = [ "multi-user.target" ];
    after = [ "systemd-udevd.service" "systemd-udev-trigger.service" ];
    restartTriggers = [ accelRules ];
    unitConfig.ConditionPathExists = "/run/udev/control";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = [
        "-${udevadm} control --reload"
        "-${udevadm} trigger --action=add --subsystem-match=accel --settle"
      ];
    };
  };
  # Power defaults for every Apple silicon Mac, the same unit as Fedora's
  # aurora-platform-core and ALARM's aurora-system-fixes. Neither setting
  # depends on the SoC. To keep the kernel's defaults:
  #   systemd.services.aurora-power-defaults.enable = false;
  systemd.services.aurora-power-defaults = {
    description = "Apple silicon power defaults";
    unitConfig = {
      ConditionFirmware = "device-tree-compatible(apple,arm-platform)";
      DefaultDependencies = false;
    };
    wantedBy = [ "sysinit.target" ];
    after = [ "systemd-sysctl.service" ];
    # aurora-power-modes records the values it finds at start as the boot
    # baseline and puts them back outside Power Saver, so they must be these.
    before = [ "sysinit.target" "aurora-power-modes.service" "shutdown.target" ];
    conflicts = [ "shutdown.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = [
        # PCIe ASPM with the L1.1 and L1.2 substates. The kernel enables them
        # per link, only where both ends advertise the substates, and keeps
        # the states a driver or the host bridge took away for hardware
        # errata off (the BCM4377 Bluetooth link; pcie-apple's tunnel root
        # ports and T6050 adopted ports). The default policy leaves the
        # substates off everywhere. A kernel booted with pcie_aspm=off
        # refuses the write; "-" lets the sysctl below run anyway.
        "-${pkgs.runtimeShell} -c 'echo powersupersave > /sys/module/pcie_aspm/parameters/policy'"
        # Realtime threads (threaded IRQs, PipeWire's data loop) get no
        # utilization floor, so they no longer run their CPU at its top clock
        # whenever they run; schedutil still raises the clock for the work
        # they do. The kernel's default is 1024.
        "${pkgs.procps}/bin/sysctl -q -w kernel.sched_util_clamp_min_rt_default=0"
      ];
    };
  };
  environment.etc."NetworkManager/conf.d/80-aurora-neo-mt7932.conf".source =
    "${pkgs.aurora-neo-platform-config}/lib/NetworkManager/conf.d/80-aurora-neo-mt7932.conf";
  # The MacBook Neo trackpad quirk (it matches only the J700 device tree).
  # libinput reads quirks from its own store path and from this file only,
  # so it goes here; a system that sets its own local overrides wins.
  environment.etc."libinput/local-overrides.quirks".source = lib.mkDefault
    "${pkgs.aurora-neo-platform-config}/share/libinput/60-aurora-neo-j700.quirks";
}
