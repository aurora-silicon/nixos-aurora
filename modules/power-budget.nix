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
      Balanced and Performance are not capped. Where the kernel budgets Power
      Saver itself (an apple-clpc platform profile), the profile is handed to
      it instead.

      Also runs aurora-power-modes for the other legs of each profile: in
      Power Saver the realtime threads lose their top-clock floor and the
      PCIe links use L1.1/L1.2, and every kernel platform-profile handler
      follows the profile unless power-profiles-daemon drives the class
      itself. `/etc/aurora/power-modes.conf` has macOS's optional "Low Power
      Mode on battery" setting (default: never); set
      `environment.etc."aurora/power-modes.conf".text` to change it.
      `systemd.services.aurora-power-modes.enable = false` keeps the budget
      without these legs.
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
    # The other legs of each profile, and Low Power Mode scheduling: the same
    # unit as aurora-platform's power/aurora-power-modes.service, which
    # Fedora and ALARM enable by preset beside the budget.
    systemd.services.aurora-power-modes = {
      description = "Power profile legs beyond the CPU budget, and Low Power Mode scheduling (Apple silicon)";
      documentation = [ "https://github.com/aurora-silicon/aurora-platform/blob/main/power/README.md" ];
      wantedBy = [ "multi-user.target" ];
      after = [ "tuned-ppd.service" "power-profiles-daemon.service" ];
      unitConfig.ConditionPathExists = "/sys/firmware/devicetree/base/cpus";
      path = [ config.systemd.package ];
      # The configuration is read at start.
      restartTriggers = [ config.environment.etc."aurora/power-modes.conf".source ];
      serviceConfig = {
        ExecStart = "${pkgs.aurora-power-budget}/libexec/aurora/aurora-power-modes";
        Restart = "on-failure";
        RestartSec = 5;
        RuntimeDirectory = "aurora-power-modes";
        # Keeps baselines.json across Restart=on-failure, so a restarted
        # daemon restores the values found at boot, not the ones its last
        # profile wrote.
        RuntimeDirectoryPreserve = "restart";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectHome = true;
        ProtectSystem = "full";
      };
    };
    # Every line commented out, so the defaults apply. A `text` set for this
    # file replaces it.
    environment.etc."aurora/power-modes.conf".source =
      lib.mkDefault "${pkgs.aurora-power-budget}/etc/aurora/power-modes.conf";
  };
}
