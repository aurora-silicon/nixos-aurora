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
        ecdsa-sk keys, pam_u2f and systemd-cryptenroll --fido2-device. Keys
        live in the Secure Enclave, which checks the Touch ID match inside
        every signature itself, so root cannot sign without a finger. The
        service does not start on a kernel without /dev/sep-key. Off by
        default. Needs an enrolled Touch ID finger.
      '';
    };
    package = lib.mkPackageOption pkgs "aurora-fido" { };
    settings = lib.mkOption {
      type = with lib.types; attrsOf (attrsOf (oneOf [ str int bool ]));
      default = { };
      example = { touchid.policy = "touchid-current"; };
      description = ''
        /etc/aurora-fido/aurora-fido.conf, by section ([touchid],
        [authenticator], [keys]). Unset keys keep the daemon's defaults; see
        docs/fido.md in aurora-sep-userspace. touchid.policy picks who may
        approve new credentials, enforced by the Secure Enclave: "auto"
        (default: touchid-or-password where the enclave can check your
        password, else touchid-any), "touchid-any" or "touchid-current"
        (the latter retires a credential when the enrolled fingers change).
      '';
    };
  };

  config = lib.mkIf cfg.enable {
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
