{ config, lib, pkgs, utils, ... }:
let
  cfg = config.aurora.fexMesa;
  provider = "/var/lib/aurora/fex/mesa-rootfs";
in {
  options.aurora.fexMesa = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Ship x86_64 and i686 Aurora Mesa and layer them over the configured FEX guest rootfs.";
    };
    rootfs = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/aurora/fex/rootfs";
      description = "Unmodified FEX distribution rootfs directory used as the guest graphics provider's lower layer.";
    };
    package = lib.mkPackageOption pkgs "aurora-fex-mesa" { };
  };
  config = lib.mkIf cfg.enable {
    assertions = [ {
      assertion = lib.hasPrefix "/" cfg.rootfs
        && !(lib.any (character: lib.hasInfix character cfg.rootfs) [ ":" "," "\n" "\\" ]);
      message = "aurora.fexMesa.rootfs must be an absolute directory without overlay mount delimiters.";
    } {
      assertion = (cfg.package.commit or null) == (pkgs.mesa.auroraCommit or "missing-host-commit");
      message = "Aurora FEX guest Mesa must use the same commit as the host driver.";
    } ];
    environment.systemPackages = [ cfg.package ];
    systemd.tmpfiles.rules = [ "d ${provider} 0755 root root -" ];
    systemd.services.aurora-fex-mesa = {
      description = "Aurora Mesa graphics provider for FEX";
      wantedBy = [ "multi-user.target" ];
      after = [ "systemd-tmpfiles-setup.service" "local-fs.target" ];
      before = [ "display-manager.service" ];
      unitConfig.RequiresMountsFor = [ cfg.rootfs ];
      unitConfig.ConditionPathIsDirectory = "${cfg.rootfs}/usr";
      restartTriggers = [ cfg.package ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = utils.escapeSystemdExecArgs [ "${pkgs.util-linux}/bin/mount" "-t" "overlay" "overlay"
          "-o" "ro,lowerdir=${cfg.package}:${cfg.rootfs}" provider ];
        ExecStop = "${pkgs.util-linux}/bin/umount ${provider}";
      };
    };
    # A rootfs is local user state, as on Fedora. Do not redirect FEX until
    # the complete graphics provider has been mounted successfully.
    environment.extraInit = ''
      if ${pkgs.util-linux}/bin/mountpoint -q ${provider}; then
        export FEX_ROOTFS="''${FEX_ROOTFS:-${provider}}"
      fi
    '';
    environment.etc."systemd/user-environment-generators/60-aurora-fex-rootfs".source =
      pkgs.writeShellScript "aurora-fex-rootfs-environment" ''
        if [ -z "''${FEX_ROOTFS:-}" ] && ${pkgs.util-linux}/bin/mountpoint -q ${provider}; then
          printf 'FEX_ROOTFS=%s\n' ${provider}
        fi
      '';
  };
}
