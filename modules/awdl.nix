{ config, lib, pkgs, ... }:
let
  cfg = config.aurora.awdl;
in {
  options.aurora.awdl = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Install the userspace for AirDrop over AWDL, the Wi-Fi link AirDrop
        runs over, on Macs with Broadcom Wi-Fi (BCM4378, BCM4387, BCM4388;
        not the Neo's MediaTek). The firmware implements AWDL and the kernel's
        brcmfmac exposes it as awdl0. Enabling this installs the tools, the
        airdrop-receiver user unit and the sleep hook, and keeps awdl0 out of
        NetworkManager. It does not create awdl0 or make the Mac
        discoverable: run `sudo awdl-up`, then
        `pkexec omdrop-discoverable start 600` for a ten-minute window, and
        `systemctl --user start airdrop-receiver` to receive. See
        share/doc/omdrop-awdl/README.md. Off by default.
      '';
    };
    package = lib.mkPackageOption pkgs "omdrop-awdl" { };
    createAtBoot = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Create awdl0 at boot (awdl0.service), idle until a window opens.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [
      cfg.package
      # awdl-up, omdrop-discoverable and send-to-peer on PATH under their own names.
      (pkgs.runCommand "omdrop-awdl-bin" { } ''
        mkdir -p $out/bin
        for f in awdl-up omdrop-discoverable send-to-peer; do
          ln -s ${cfg.package}/libexec/omdrop/$f $out/bin/$f
        done
      '')
    ];
    # Units (awdl0.service, awdl-warmup.service, the user airdrop-receiver) and
    # the system-sleep hook that removes awdl0 before suspend.
    systemd.packages = [ cfg.package ];
    systemd.services.awdl0.wantedBy = lib.mkIf cfg.createAtBoot [ "multi-user.target" ];
    networking.networkmanager.unmanaged = [ "interface-name:awdl0" ];
    security.polkit.enable = true;
  };
}
