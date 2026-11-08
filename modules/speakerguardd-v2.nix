{ config, lib, ... }:
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
  config.assertions = [ {
    assertion = !config.aurora.speakerguardd.v2.enable;
    message = "Aurora's speakerguardd v2 rollout is held. Remove aurora.speakerguardd.v2.enable = true to use the restored legacy protection stack.";
  } ];
}
