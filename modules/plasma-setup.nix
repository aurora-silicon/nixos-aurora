{ config, lib, pkgs, ... }:
# Plasma Setup creates the owner account on KDE images. nixpkgs packages it
# without a NixOS module; this wires up what its build installs for systemd,
# sysusers, tmpfiles, polkit and D-Bus. The flag file, the unit's condition and
# the account helper's tool search are patched for NixOS (overlay.nix).
#
# At first boot plasma-setup.service writes an SDDM autologin for the
# plasma-setup system user; that session runs the wizard, which creates the
# owner (wheel) through its KAuth helper, writes /etc/plasma-setup-done and
# logs out to the greeter. modules/firstboot.nix orders it after Aurora's disk
# step. Accounts are found through /etc/login.defs (UID 1000-29999 on NixOS),
# so the nixbld build users (30001 and up) never count as an owner.
let
  cfg = config.aurora.plasmaSetup;
  package = pkgs.kdePackages.plasma-setup;
in {
  options.aurora.plasmaSetup.enable = lib.mkOption {
    type = lib.types.bool;
    default = config.aurora.desktop == "kde" && config.aurora.imageLayout != null;
    defaultText = lib.literalExpression ''config.aurora.desktop == "kde" && config.aurora.imageLayout != null'';
    description = "Create the owner account at first boot with Plasma Setup.";
  };
  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = config.services.displayManager.sddm.enable;
        message = "aurora.plasmaSetup requires SDDM, whose autologin starts the setup session.";
      }
      {
        assertion = config.users.mutableUsers;
        message = "aurora.plasmaSetup creates the owner imperatively and requires users.mutableUsers.";
      }
    ];
    # Policy and polkit rules (share/polkit-1), the wizard's pages and the
    # tools its session uses.
    environment.systemPackages = [ package ];
    # The KAuth helper's D-Bus activation file and bus policy.
    services.dbus.packages = [ package ];
    # plasma-setup.service, enabled as its [Install] section asks.
    systemd.packages = [ package ];
    systemd.services.plasma-setup.wantedBy = [ "multi-user.target" ];
    # The setup user's home with the wizard's autostart entry, recreated in
    # /run at every boot.
    systemd.tmpfiles.packages = [ package ];
    # The package's sysusers.d entry: u plasma-setup - "Plasma Setup" /run/plasma-setup /bin/sh
    users.users.plasma-setup = {
      isSystemUser = true;
      group = "plasma-setup";
      description = "Plasma Setup";
      home = "/run/plasma-setup";
      createHome = false;
      shell = pkgs.bashInteractive;
    };
    users.groups.plasma-setup = { };
    # NixOS restricts SDDM autologin to UID 1000 and up; the setup user is a
    # system user, which keeps it out of every account count. Let SDDM start
    # its session (the autologin configuration that names it is root's) and
    # keep the UID check for everyone else.
    security.pam.services.sddm-autologin.rules.auth.plasma-setup = {
      order = (config.security.pam.services.sddm-autologin.rules.auth.sddm-autologin-user.order or 10200) - 1;
      control = "sufficient";
      modulePath = "${config.security.pam.package}/lib/security/pam_succeed_if.so";
      settings.quiet = true;
      args = lib.mkAfter [ "user" "=" "plasma-setup" ];
    };
  };
}
