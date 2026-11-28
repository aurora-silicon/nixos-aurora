{ pkgs, nixpkgs, makeSystem }:
let
  inherit (nixpkgs) lib;
  marker = pkgs.writeText "aurora-grub-extra-file" "host-owned GRUB file\n";
  installed = (makeSystem "minimal").extendModules {
    modules = [ {
      system.stateVersion = "25.11";
      boot.loader.grub.extraFiles."host/marker" = marker;
    } ];
  };
  disabled = installed.extendModules {
    modules = [ { aurora.stage2.enable = false; } ];
  };
  customPortal = installed.extendModules {
    modules = [ { xdg.portal.config.common.default = [ "host-portal" ]; } ];
  };
  noSpeakerUpgrade = installed.extendModules {
    # The platform turns it on unconditionally; only mkForce turns it off.
    modules = [ { aurora.speakerguardd.upgrade.enable = lib.mkForce false; } ];
  };
  upgradePackage = installed.pkgs.aurora-speaker-upgrade;
  # avd-fw 6062e851, whose 0x12000-byte v4 image the T8122 (M3) device tree
  # of linux#2586 no longer fits.
  olderAvdFirmware = installed.extendModules {
    modules = [ { nixpkgs.overlays = lib.mkAfter [ (_: prev: {
      # Only the version matters here: the platform assertion compares it.
      aurora-avd-firmware = prev.aurora-avd-firmware.overrideAttrs {
        version = "0.1-unstable-2026-11-01.2";
        __intentionallyOverridingVersion = true;
      };
    }) ]; } ];
  };
  awdl = installed.extendModules {
    modules = [ { aurora.awdl.enable = true; } ];
  };
  awdlSleepHook = "systemd/system-sleep/omdrop-awdl";
  refusesAvdFirmware = system: lib.any (entry: !entry.assertion && lib.hasInfix "aurora-avd-firmware" entry.message)
    system.config.assertions;
  preservesHostFile = config:
    config.boot.loader.grub.extraFiles."host/marker" == marker
    && !(config.boot.loader.grub.extraFiles ? "m1n1/boot.bin");
in
assert lib.assertMsg (installed.config.system.stateVersion == "25.11")
  "Aurora must preserve the host's initial stateVersion";
assert lib.assertMsg (preservesHostFile installed.config && preservesHostFile disabled.config)
  "Aurora must preserve host GRUB files and suppress the unchecked Stage 2 copy";
assert lib.assertMsg
  (installed.config.xdg.portal.config.common.default == "gtk"
    && customPortal.config.xdg.portal.config.common.default == "host-portal")
  "The minimal portal backend must be selected explicitly and remain overridable";
assert lib.assertMsg
  (lib.hasInfix "aurora-install-stage2" installed.config.boot.loader.grub.extraInstallCommands
    && !(lib.hasInfix "aurora-install-stage2" disabled.config.boot.loader.grub.extraInstallCommands))
  "Disabling Aurora Stage 2 updates must leave the ESP Stage 2 unchanged";
assert lib.assertMsg
  (installed.config.aurora.speakerguardd.upgrade.enable
    && lib.elem upgradePackage installed.config.environment.systemPackages
    && lib.elem upgradePackage installed.config.systemd.packages
    && (installed.config.systemd.services.aurora-speaker-upgrade.wantedBy or [ ]) == [ "multi-user.target" ])
  "Speaker migration must be installed and run at boot by default";
assert lib.assertMsg
  (!(lib.elem upgradePackage noSpeakerUpgrade.config.environment.systemPackages)
    && !(lib.elem upgradePackage noSpeakerUpgrade.config.systemd.packages)
    && (noSpeakerUpgrade.config.systemd.services.aurora-speaker-upgrade.wantedBy or [ ]) == [ ])
  "Opting out of speaker migration must remove its tool and units";
assert lib.assertMsg
  (installed.config.boot.kernelPackages.kernel.auroraMinAvdFirmware == "0.1-unstable-2026-11-21"
    && !(refusesAvdFirmware installed) && refusesAvdFirmware olderAvdFirmware
    && lib.hasInfix "('v4-t0', 0x10000, '" (builtins.readFile ../firmware/check-avd.py))
  "The kernel must require the avd-fw whose 64 KiB v4 image fits the T8122 SRAM window, and refuse an older one";
assert lib.assertMsg
  ((awdl.config.environment.etc.${awdlSleepHook}.source or null)
      == "${awdl.pkgs.omdrop-awdl}/lib/systemd/system-sleep/omdrop-awdl"
    && !(installed.config.environment.etc ? ${awdlSleepHook}))
  "AirDrop over AWDL must install its system-sleep hook where systemd-sleep runs it, and only when enabled";
pkgs.runCommand "aurora-module-composition" { } "touch $out"
