{ config, lib, pkgs, ... }:
let
  cfg = config.aurora.flatpak;
  manager = pkgs.writeShellApplication {
    name = "aurora-flatpak-gl";
    runtimeInputs = [ config.services.flatpak.package pkgs.ostree pkgs.python3 ];
    text = ''
      exec python3 ${../flatpak-gl}/manage.py "$@" \
        --repo ${lib.escapeShellArg (toString cfg.package)} --commit ${cfg.package.commit}
    '';
  };
in {
  options.aurora.flatpak = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable Flatpak with Aurora Mesa for the 25.08 and 26.08 runtimes.";
    };
    package = lib.mkPackageOption pkgs "aurora-flatpak-gl" { };
  };
  config = lib.mkIf cfg.enable {
    assertions = [ {
      assertion = config.services.flatpak.enable;
      message = "aurora.flatpak.enable requires services.flatpak.enable.";
    } ];
    services.flatpak.enable = lib.mkDefault true;
    xdg.portal.enable = lib.mkDefault true;
    xdg.portal.extraPortals = lib.mkIf (config.aurora.desktop == "minimal") [ pkgs.xdg-desktop-portal-gtk ];
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
      after = [ "systemd-tmpfiles-setup.service" ];
      before = [ "display-manager.service" ];
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
