{ config, lib, pkgs, ... }:
let
  daemons = [ "malcontent-timerd" "malcontent-timer-extension-agent" "malcontent-webd" ];
  signalFix = name: {
    overrideStrategy = "asDropin";
    # Keep the retirement note in each generated drop-in, including on
    # nixpkgs revisions that do not yet ship these optional daemons.
    text = ''
      # Remove when malcontent includes upstream af8226a7d3c3
      # (Fix system call filters for signal handling) and exits cleanly
      # on SIGTERM as the init of its PrivatePIDs namespace.
      [Service]
      SystemCallFilter=@signal
      ${lib.optionalString (lib.elem (lib.removeSuffix ".service" name) daemons) "SuccessExitStatus=71"}
    '';
  };
  wakeForNetwork = pkgs.writeShellScriptBin "aurora-wake-for-network"
    (builtins.replaceStrings [ "export PATH=/usr/sbin:/usr/bin" ]
      [ "export PATH=${lib.makeBinPath [ pkgs.ethtool pkgs.iw pkgs.coreutils pkgs.gnugrep ]}" ]
      (builtins.readFile ./aurora-wake-for-network.sh));
in {
  options.aurora.systemFixes.wakeForNetwork = lib.mkOption {
    type = lib.types.enum [ "power-adapter" "always" "never" ];
    default = "power-adapter";
    description = ''
      Wake for network access (magic packet on wired interfaces that support
      it and on Wi-Fi phys with magic-packet WoWLAN). The default follows the
      power adapter, as macOS laptops do: armed on AC, disarmed on battery.
    '';
  };
  options.aurora.systemFixes.malcontentSignal = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = ''
      Add the signal-handling and exit-status drop-ins for malcontent's optional
      daemons. This does not start or install absent daemons; false omits the
      drop-ins and retains their packaged behavior.
    '';
  };
  options.aurora.systemFixes.nmDispatcherPersist = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = ''
      Run NetworkManager's dispatcher with `--persist` and stop it after
      NetworkManager, avoiding failed event activation during shutdown. Used
      only when NetworkManager is enabled; false retains its packaged lifecycle.
    '';
  };
  options.aurora.systemFixes.nmKeepWakeOnLan = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = "Keep a Wake-on-LAN/WLAN device that is still activated after wake instead of reconnecting it.";
  };
  config = lib.mkMerge [
    (lib.mkIf config.aurora.systemFixes.malcontentSignal {
      systemd.units = lib.genAttrs (map (name: "${name}.service")
        (daemons ++ [ "malcontent-webd-update" ])) signalFix;
    })
    (lib.mkIf (config.aurora.systemFixes.nmKeepWakeOnLan && config.networking.networkmanager.enable) {
      # NetworkManager leaves Wake-on-LAN devices up at sleep so they stay
      # armed, but at wake it takes every one of them down and reconnects it,
      # even when its Wi-Fi association or Ethernet carrier survived. The
      # patch keeps such a device and only refreshes its IP configuration.
      # Same patch as fedora-aurora's networkmanager-aurora (1.58.1).
      networking.networkmanager.package = lib.mkDefault (pkgs.networkmanager.overrideAttrs (old: {
        patches = (old.patches or [ ]) ++ [ ../patches/networkmanager-keep-activated-wake-on-lan.patch ];
      }));
    })
    (lib.mkIf (config.aurora.systemFixes.nmDispatcherPersist && config.networking.networkmanager.enable) {
      # NetworkManager dispatches dns-change and connectivity-change events
      # while it stops. The dispatcher exits after 10 s idle, and once shutdown
      # is queued systemd refuses to start it, so its D-Bus activation fails on
      # every shutdown. NetworkManager issue 1643.
      systemd.services.NetworkManager-dispatcher = {
        before = [ "NetworkManager.service" ];
        serviceConfig.ExecStart = [ "" "${config.networking.networkmanager.package}/libexec/nm-dispatcher --persist" ];
      };
    })
    {
      # Same policy script and udev triggers as fedora-aurora's aurora-platform.
      environment.etc."aurora/wake-for-network".text = config.aurora.systemFixes.wakeForNetwork + "\n";
      services.udev.extraRules = ''
        SUBSYSTEM=="power_supply", ACTION=="change", ATTR{type}=="Mains", RUN+="${wakeForNetwork}/bin/aurora-wake-for-network"
        SUBSYSTEM=="net", ACTION=="add", ENV{DEVTYPE}!="wlan", RUN+="${wakeForNetwork}/bin/aurora-wake-for-network"
        SUBSYSTEM=="ieee80211", ACTION=="add", RUN+="${wakeForNetwork}/bin/aurora-wake-for-network"
      '';
    }
    {
      # Only contributes ordering when this optional swapfile unit exists.
      # Btrfs activates swapfiles under an exclusive filesystem operation.
      systemd.units."var-swap-swapfile2.swap" = {
        overrideStrategy = "asDropin";
        text = ''
          [Unit]
          After=var-swap-swapfile.swap
        '';
      };
    }
  ];
}
