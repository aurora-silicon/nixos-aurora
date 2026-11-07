{ config, lib, pkgs, ... }:
let
  cfg = config.aurora.sepLuks;
  plugins = "${cfg.package}/lib/cryptsetup";
  initrdLoad = "${cfg.package}/lib/aurora-sep/initrd/aurora-sep-initrd-load";
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
      '';
    };
    initrd.enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Open SEP-enrolled volumes in the initrd too, the root volume included.
        Needs boot.initrd.systemd.enable and a kernel whose apple_sep has the
        key-store-only attach phase (the keystore_only parameter); with an
        older kernel the initrd leaves the driver alone and those volumes ask
        for their passphrase. The SEP key store files from /var/lib go into the
        initrd through boot.initrd.secrets (never the Nix store), so they must
        exist when the boot loader is installed: enable Touch ID or run the SEP
        once first. Rebuild after the key store changes. Every volume keeps its
        passphrase.
      '';
    };
    package = lib.mkPackageOption pkgs "aurora-sep-luks" { };
  };

  config = lib.mkIf cfg.enable (lib.mkMerge [
    {
      environment.systemPackages = [ cfg.package ];
      # nixpkgs' cryptsetup loads token plugins by name through the library
      # search path (relative-token-path.patch), so point crypttab's
      # systemd-cryptsetup instances at the plugin.
      systemd.services."systemd-cryptsetup@" = {
        overrideStrategy = "asDropin";
        environment.LD_LIBRARY_PATH = plugins;
      };
    }
    (lib.mkIf cfg.initrd.enable {
      assertions = [{
        assertion = config.boot.initrd.systemd.enable;
        message = "aurora.sepLuks.initrd.enable needs boot.initrd.systemd.enable = true (systemd-cryptsetup in the initrd).";
      }];
      # Loaded by aurora-sep-initrd below with keystore_only=1, never by alias.
      boot.initrd.availableKernelModules = [ "apple_sep" "algif_aead" "ccm" "ctr" ];
      boot.initrd.secrets = {
        "/var/lib/aurora-sep-keybag.bin" = "/var/lib/aurora-sep-keybag.bin";
        "/var/lib/aurora-sep-refkey.bin" = "/var/lib/aurora-sep-refkey.bin";
      };
      boot.initrd.systemd.storePaths = [ plugins initrdLoad ];
      boot.initrd.systemd.services.aurora-sep-initrd = {
        description = "Secure Enclave key store for LUKS2 unlock";
        unitConfig = {
          DefaultDependencies = false;
          ConditionPathExists = "/var/lib/aurora-sep-keybag.bin";
        };
        after = [ "systemd-modules-load.service" ];
        before = [ "cryptsetup-pre.target" ];
        wants = [ "cryptsetup-pre.target" ];
        wantedBy = [ "cryptsetup-pre.target" ];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          ExecStart = initrdLoad;
        };
      };
      # The SEP key store can take most of a minute after boot (about 43 s on
      # the J700); wait that long before the passphrase prompt.
      boot.initrd.systemd.services."systemd-cryptsetup@" = {
        overrideStrategy = "asDropin";
        environment = {
          LD_LIBRARY_PATH = plugins;
          AURORA_SEP_WAIT = "90";
        };
      };
    })
  ]);
}
