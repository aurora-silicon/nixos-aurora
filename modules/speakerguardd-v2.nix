{ config, lib, pkgs, ... }:
{
  # Keep explicit enable = false configurations compatible while retiring
  # the preview package, units and fleet gates from shipped systems.
  options.aurora.speakerguardd.v2.enable = lib.mkOption {
    type = lib.types.bool;
    default = false;
    description = "The speakerguardd v2 preview is held; use the legacy Asahi protection stack.";
  };
  imports = [
    (lib.mkRemovedOptionModule [ "aurora" "speakerguardd" "v2" "package" ]
      "The v2 preview package is retired while its rollout is held.")
    (lib.mkRemovedOptionModule [ "aurora" "speakerguardd" "v2" "replaceLegacy" ]
      "The established Asahi protection stack is restored by default.")
  ];
  config = {
    assertions = [ {
      assertion = !config.aurora.speakerguardd.v2.enable;
      message = "Aurora's speakerguardd v2 rollout is held. Remove aurora.speakerguardd.v2.enable = true to use the restored legacy protection stack.";
    } ];
    # The preview linked its generated PipeWire and WirePlumber configuration
    # into each user's ~/.config, pointing into /run/speakerguardd-graph. Nothing
    # creates that directory without v2, so the links dangle and PipeWire logs an
    # error at every login. Remove only links into that directory, at every boot
    # and switch; /var/lib/speakerguardd stays for aurora-speaker-upgrade.
    system.activationScripts.aurora-audio-v2-cleanup.text = let
      cleanup = pkgs.writeShellApplication {
        name = "aurora-audio-v2-cleanup";
        runtimeInputs = [ pkgs.getent pkgs.coreutils ];
        # writeShellApplication writes its own shebang (shellcheck SC1128).
        text = lib.removePrefix "#!/bin/sh\n" (builtins.readFile ./aurora-audio-v2-cleanup);
      };
    in "${cleanup}/bin/aurora-audio-v2-cleanup || true";
  };
}
