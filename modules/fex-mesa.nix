{ config, lib, pkgs, utils, ... }:
let
  cfg = config.aurora.fexMesa;
  provider = "/var/lib/aurora/fex/mesa-rootfs";
  # Unit path directives expand percent specifiers. RequiresMountsFor also
  # splits words, so quote its path separately from the ExecStart arguments.
  unitRootfs = lib.replaceStrings [ "%" ] [ "%%" ] cfg.rootfs;
in {
  options.aurora.fexMesa = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Mount x86_64 and i686 Aurora Mesa over the guest rootfs at
        `/var/lib/aurora/fex/mesa-rootfs`. Set `FEX_ROOTFS` only when the provider
        is mounted and the user has not set it. False removes this integration
        and unmounts the provider on a switch; guest distribution files remain.
      '';
    };
    rootfs = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/aurora/fex/rootfs";
      example = "/srv/fex/Fedora";
      description = ''
        Absolute path to an unpacked FEX guest distribution containing `usr`.
        It is neither downloaded nor modified; the service skips a missing
        `usr` directory. Colons, commas, backslashes and newlines are unsupported
        because this path is an overlay mount's lower layer.
      '';
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
      unitConfig.RequiresMountsFor = [ (builtins.toJSON unitRootfs) ];
      unitConfig.ConditionPathIsDirectory = "${unitRootfs}/usr";
      # Nix never overwrites the mounted store layer. Stop the old unit before
      # switching, then mount the new immutable path (also on rollback).
      stopIfChanged = true;
      restartIfChanged = true;
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
