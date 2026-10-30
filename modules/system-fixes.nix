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
  config = lib.mkIf config.aurora.systemFixes.malcontentSignal {
    systemd.units = lib.genAttrs (map (name: "${name}.service")
      (daemons ++ [ "malcontent-webd-update" ])) signalFix;
  };
}
