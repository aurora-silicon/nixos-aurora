{ config, lib, ... }:
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
    description = "Allow malcontent's optional daemons to handle SIGTERM and stop promptly.";
  };
  options.aurora.systemFixes.nmDispatcherPersist = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = "Keep NetworkManager's dispatcher running until NetworkManager has stopped.";
  };
  config = lib.mkMerge [
    (lib.mkIf config.aurora.systemFixes.malcontentSignal {
      systemd.units = lib.genAttrs (map (name: "${name}.service")
        (daemons ++ [ "malcontent-webd-update" ])) signalFix;
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
