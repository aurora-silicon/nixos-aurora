{ config, lib, pkgs, ... }:
let
  cfg = config.aurora.sepLuks;
in {
  options.aurora.sepLuks = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Install aurora-sep-cryptenroll and its libcryptsetup token plugin, which
        unlock LUKS2 volumes with this Mac's Secure Enclave the way
        systemd-cryptenroll --tpm2-device=auto does with a TPM. Nothing is
        enrolled by this option: run aurora-sep-cryptenroll for each volume.
        The root volume is not supported yet.
      '';
    };
    package = lib.mkPackageOption pkgs "aurora-sep-luks" { };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];
    # nixpkgs' cryptsetup loads token plugins by name through the library
    # search path (relative-token-path.patch), so point crypttab's
    # systemd-cryptsetup instances at the plugin.
    systemd.services."systemd-cryptsetup@" = {
      overrideStrategy = "asDropin";
      environment.LD_LIBRARY_PATH = "${cfg.package}/lib/cryptsetup";
    };
  };
}
