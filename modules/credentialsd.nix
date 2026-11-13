{ config, lib, pkgs, ... }:
let
  cfg = config.aurora.credentialsd;
in {
  options.aurora.credentialsd = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = config.aurora.desktop != "minimal";
      defaultText = lib.literalExpression ''config.aurora.desktop != "minimal"'';
      description = ''
        credentialsd behind xdg-desktop-portal's experimental Credential
        portal, as on Fedora and Arch desktop images. Browsers that use the
        portal reach security keys, phones (hybrid) and platform passkey
        providers through it; with aurora.fido.enable, aurora-fido's Secure
        Enclave agent (aurora-passkeyd) registers as a provider, so Touch ID
        passkeys work. On by default on desktop images.
      '';
    };
    package = lib.mkPackageOption pkgs "credentialsd" { };
  };

  config = lib.mkIf cfg.enable {
    # credentialsd.portal names the Credential backend; Aurora's
    # xdg-desktop-portal uses it without a portals.conf entry.
    xdg.portal.extraPortals = [ cfg.package ];
    services.dbus.packages = [ cfg.package ];
    systemd.packages = [ cfg.package ];
    environment.systemPackages = [ cfg.package ];
    # The portal only starts the experimental interface with this flag.
    systemd.user.services.xdg-desktop-portal.environment.XDG_DESKTOP_PORTAL_ENABLE_EXPERIMENTAL = "credential";
    environment.etc."credentialsd/providers/org.aurora.Passkeys.conf" = lib.mkIf config.aurora.fido.enable {
      source = ../sep/credentialsd-org.aurora.Passkeys.conf;
    };
  };
}
