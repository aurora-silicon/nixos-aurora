{ config, lib, pkgs, ... }:
let
  cfg = config.aurora.flatpak;
  managerSource = lib.fileset.toSource {
    root = ../flatpak-gl;
    fileset = lib.fileset.unions [
      ../flatpak-gl/manage.py ../flatpak-gl/validate-repository.py ../flatpak-gl/sdk-lock.json
    ];
  };
  manager = pkgs.writeShellApplication {
    name = "aurora-flatpak-gl";
    runtimeInputs = [ config.services.flatpak.package pkgs.ostree pkgs.python3 ];
    text = ''
      exec python3 ${managerSource}/manage.py "$@" \
        --repo ${lib.escapeShellArg (toString cfg.package)} --commit ${lib.escapeShellArg cfg.package.commit}
    '';
  };
in {
  options.aurora.flatpak = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Enable Flatpak and install pinned Aurora GL runtime extensions before
        desktop login. Supply GL driver defaults without replacing an explicit
        `FLATPAK_GL_DRIVERS`. False removes Aurora's managed extensions and
        overrides on a switch; Flatpak itself follows its other configuration.
      '';
    };
    package = lib.mkPackageOption pkgs "aurora-flatpak-gl" { };
  };
  config = lib.mkIf cfg.enable {
    assertions = [ {
      assertion = config.services.flatpak.enable;
      message = "aurora.flatpak.enable requires services.flatpak.enable.";
    } {
      assertion = (cfg.package.commit or null) == (pkgs.mesa.auroraCommit or "missing-host-commit");
      message = "Aurora Flatpak GL must use the same Mesa commit as the host driver.";
    } ];
    services.flatpak.enable = lib.mkDefault true;
    xdg.portal.enable = lib.mkDefault true;
    xdg.portal.extraPortals = lib.mkIf (config.aurora.desktop == "minimal") [ pkgs.xdg-desktop-portal-gtk ];
    xdg.portal.config.common.default = lib.mkIf (config.aurora.desktop == "minimal") (lib.mkDefault [ "gtk" ]);
    environment.systemPackages = [ manager ];
    # Preserve explicit user choices in login shells and user systemd services.
    environment.extraInit = ''
      export FLATPAK_GL_DRIVERS="''${FLATPAK_GL_DRIVERS:-aurora:default:host}"
    '';
    environment.etc."environment.d/60-aurora-flatpak-gl.conf".text = ''
      FLATPAK_GL_DRIVERS=''${FLATPAK_GL_DRIVERS:-aurora:default:host}
    '';
    systemd.services.aurora-flatpak-gl = {
      description = "Aurora Mesa for Flatpak applications";
      wantedBy = [ "multi-user.target" ];
      # Keep installed runtimes across shutdown. Explicit stops on a switch
      # or disable still run ExecStop and remove only this provider's state.
      unitConfig.DefaultDependencies = false;
      after = [ "local-fs.target" "systemd-tmpfiles-setup.service" "dbus.service" ];
      before = [ "multi-user.target" "display-manager.service" ];
      restartTriggers = [ cfg.package ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = "${manager}/bin/aurora-flatpak-gl enable";
        ExecStop = "${manager}/bin/aurora-flatpak-gl disable";
        TimeoutStartSec = 300;
      };
    };
  };
}
