{ config, lib, pkgs, ... }:
# GNOME Initial Setup creates the owner account on GNOME images. GDM starts
# its new-user mode instead of the greeter while no account exists; nixpkgs'
# GDM never does, so this enables it on Aurora images:
#
# - GDM looks for gnome-initial-setup.session under its own store path. The
#   display manager runs a GDM built to look in the system profile instead
#   (aurora-gdm in overlay.nix).
# - NixOS marks the setup as already run at every boot. The marker is removed
#   before the display manager starts, only while no person account exists.
# - Without systemd userdb, GDM runs the setup session as a preallocated
#   gnome-initial-setup user, whose group GNOME Initial Setup's polkit rules
#   trust; gdm-launch-environment admits that group as upstream does.
# - nixpkgs' module would shadow the session's systemd template with a whole
#   unit; it is kept a drop-in.
# - nixpkgs' vendor file skipped the account and password pages (overlay.nix).
#
# The setup creates the owner through AccountsService as an administrator
# (wheel), then GDM signs the owner in.
let
  cfg = config.aurora.gnomeInitialSetup;
  marker = "/run/gdm/gdm.ran-initial-setup";
in {
  options.aurora.gnomeInitialSetup.enable = lib.mkOption {
    type = lib.types.bool;
    default = config.aurora.desktop == "gnome" && config.aurora.imageLayout != null;
    defaultText = lib.literalExpression ''config.aurora.desktop == "gnome" && config.aurora.imageLayout != null'';
    description = "Create the owner account at first boot with GNOME Initial Setup.";
  };
  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = config.services.displayManager.gdm.enable;
        message = "aurora.gnomeInitialSetup requires GDM, which starts the setup session.";
      }
      {
        assertion = config.users.mutableUsers;
        message = "aurora.gnomeInitialSetup creates the owner imperatively and requires users.mutableUsers.";
      }
    ];
    services.gnome.gnome-initial-setup.enable = true;
    services.accounts-daemon.enable = true;
    services.displayManager.generic.execCmd = lib.mkForce "exec ${pkgs.aurora-gdm}/bin/gdm";
    # The setup session's gnome-session file and gnome-shell mode.
    services.displayManager.gdm.extraPackages = [ pkgs.gnome-initial-setup ];
    # GDM names each setup session's user gnome-initial-setup, then
    # gnome-initial-setup-2 and so on while an earlier one is still allocated
    # (a retried session). Preallocate five, as nixpkgs does for gdm-greeter,
    # in GDM's greeter UID range just after those.
    users.users = lib.listToAttrs (lib.genList (i: let
      name = "gnome-initial-setup" + lib.optionalString (i > 0) "-${toString (i + 1)}";
    in lib.nameValuePair name {
      isSystemUser = true;
      uid = 60583 + i;
      group = "gnome-initial-setup";
      description = "GNOME Initial Setup";
      # GDM creates this home for the session, as for its greeter users.
      home = "/run/gdm/home/${name}";
    }) 5);
    users.groups.gnome-initial-setup = { };
    # nixpkgs' GNOME Initial Setup module adds a Wants= to this template
    # instance. As a whole unit file it would replace gnome-session@.target
    # for the instance, dropping the session manager and the initialized
    # target, so the setup session would fail as soon as it started. Keep it
    # a drop-in, like the package's own gnome-initial-setup.conf.
    systemd.user.targets."gnome-session@gnome-initial-setup".overrideStrategy = "asDropin";
    security.pam.services.gdm-launch-environment.rules = lib.genAttrs [ "auth" "account" "session" ] (_: {
      gdm-user.args = lib.mkForce [ "audit" "quiet_success" "user" "ingroup" "gdm:gnome-initial-setup" ];
    });
    systemd.services.aurora-gnome-initial-setup = {
      description = "Let GDM run GNOME Initial Setup while no owner exists";
      wantedBy = [ "display-manager.service" ];
      before = [ "display-manager.service" ];
      after = [ "systemd-tmpfiles-setup.service" "aurora-firstboot.service" ];
      unitConfig.ConditionPathExists = marker;
      serviceConfig.Type = "oneshot";
      path = [ pkgs.glibc.getent pkgs.gawk pkgs.coreutils ];
      script = ''
        # A person's account, as aurora-firstboot counts it: a regular UID and
        # a login shell (the Nix build users and GDM's own users use nologin).
        if getent passwd | awk -F: '$3 >= 1000 && $3 < 60000 && $7 !~ /(nologin|false)$/ { found = 1 } END { exit !found }'; then
          exit 0
        fi
        rm -f -- ${marker}
      '';
    };
    # aurora-firstboot cannot see this wiring (NixOS's display-manager.service
    # is not gdm.service): declare that the desktop's setup creates the owner.
    environment.etc."aurora/desktop-account-setup".text = "gnome-initial-setup\n";
  };
}
