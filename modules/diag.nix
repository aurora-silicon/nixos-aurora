{ config, lib, pkgs, ... }:
let
  cfg = config.aurora.diag;
in {
  options.aurora.diag = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Install aurora-diag, the bring-up and regression tool: sensors,
        clocks, hardware blocks, services and GPU APIs with what works and
        what does not, `check`, `snapshot`, `diff` and `report` for
        comparing kernels, and `aurora-panic-log` for the last panic iBoot
        kept. Fedora and ALARM ship the same commit as the opt-in
        `aurora-diag` package. Off by default.
      '';
    };
    package = lib.mkPackageOption pkgs "aurora-diag" { };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];
  };
}
