{ config, lib, pkgs, ... }:
let
  cfg = config.aurora.fido;
  conf = pkgs.writeText "aurora-fido.conf" (lib.generators.toINI { } cfg.settings);
in {
  options.aurora.fido = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Run aurora-fidod, which makes this Mac's Secure Enclave and Touch ID a
        FIDO2/U2F security key: WebAuthn and passkeys in browsers, SSH
        ecdsa-sk keys, pam_u2f and systemd-cryptenroll --fido2-device. Every
        operation asks for a Touch ID match. Keys live in the Secure Enclave
        when the kernel has /dev/sep-key and are sealed by it otherwise (root
        on this Mac can copy sealed keys); `aurora-fido status` says which.
        Off by default. Needs Touch ID (fprintd with an enrolled finger).
      '';
    };
    package = lib.mkPackageOption pkgs "aurora-fido" { };
    settings = lib.mkOption {
      type = with lib.types; attrsOf (attrsOf (oneOf [ str int bool ]));
      default = { };
      example = { touchid.policy = "touchid-current"; keys.store = "sep-key"; };
      description = ''
        /etc/aurora-fido/aurora-fido.conf, by section ([touchid],
        [authenticator], [keys]). Unset keys keep the daemon's defaults; see
        docs/fido.md in aurora-sep-userspace. touchid.policy picks who may
        approve new credentials, as on macOS: "touchid-or-password" (default:
        Touch ID, or your password in the polkit dialog), "touchid-any" or
        "touchid-current" (Touch ID only; the latter retires a credential
        when the enrolled fingers change).
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [{
      assertion = config.services.fprintd.enable;
      message = "aurora.fido.enable needs Touch ID (services.fprintd.enable, set by Aurora's Touch ID module).";
    }];
    boot.kernelModules = [ "uhid" ];
    environment.systemPackages = [ cfg.package ];
    environment.etc."aurora-fido/aurora-fido.conf".source = conf;
    services.udev.packages = [ cfg.package ];
    systemd.packages = [ cfg.package ];
    systemd.services.aurora-fido = {
      wantedBy = [ "multi-user.target" ];
      # loginctl (whose finger), setpriv + notify-send + gdbus (the notification).
      path = [ config.systemd.package pkgs.util-linux pkgs.libnotify pkgs.glib.bin ];
      restartTriggers = [ conf ];
    };
  };
}
