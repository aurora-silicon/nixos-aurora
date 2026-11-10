{ config, lib, pkgs, ... }:
let cfg = config.aurora.powerBudget;
in {
  options.aurora.powerBudget.enable = lib.mkOption {
    type = lib.types.bool;
    default = config.services.power-profiles-daemon.enable;
    defaultText = lib.literalExpression "config.services.power-profiles-daemon.enable";
    description = ''
      Give the Power Saver profile a CPU power budget, as macOS Low Power Mode
      does: every 100 ms the budget is split across the CPU clusters from the
      device tree energy model and each cluster is capped to its share.
      Balanced and Performance are untouched.
    '';
  };

  config = lib.mkIf cfg.enable {
    systemd.services.aurora-power-budget = {
      description = "CPU power budget for the power-saver profile (Apple silicon)";
      documentation = [ "https://github.com/aurora-silicon/aurora-platform/blob/main/power/README.md" ];
      wantedBy = [ "multi-user.target" ];
      after = [ "power-profiles-daemon.service" ];
      unitConfig.ConditionPathExists = "/sys/firmware/devicetree/base/cpus";
      path = [ config.systemd.package ];
      serviceConfig = {
        ExecStart = "${pkgs.aurora-power-budget}/libexec/aurora/aurora-power-budget";
        Restart = "on-failure";
        RestartSec = 5;
        RuntimeDirectory = "aurora-power-budget";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectHome = true;
        ProtectSystem = "full";
      };
    };
  };
}
