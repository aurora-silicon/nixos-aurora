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
in {
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
  options.aurora.systemFixes.drkonqiOrdering = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = ''
      Break the ordering cycle that drkonqi's coredump cleanup timer and sentry
      path units create, which makes systemd delete a stop job every time a
      Plasma session stops (KDE bug 528003). Used only with Plasma; false
      retains the packaged units unchanged.
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
    (lib.mkIf (config.aurora.systemFixes.drkonqiOrdering && config.services.desktopManager.plasma6.enable) {
      # drkonqi orders these user units after the target that their default
      # dependencies order them before: the cleanup timer after timers.target,
      # the sentry path after default.target, which comes after paths.target.
      # Keep the dependencies a user unit needs without that implicit ordering.
      # Same drop-in as Fedora's aurora-release and ALARM's aurora-system-fixes.
      systemd.user.units = lib.genAttrs [ "drkonqi-coredump-cleanup.timer" "drkonqi-sentry-postman.path" ] (_: {
        overrideStrategy = "asDropin";
        text = ''
          # KDE bug 528003. Remove when drkonqi's units no longer order
          # themselves after the targets they are wanted by.
          [Unit]
          DefaultDependencies=no
          Conflicts=shutdown.target
          Before=shutdown.target
        '';
      });
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
