{ config, lib, pkgs, ... }:
let
  cfg = config.aurora.sep;
in {
  # nixpkgs offers a fingerprint to every PAM service once fprintd is on; here
  # a service takes one only when it says so (see config below).
  options.security.pam.services = lib.mkOption {
    type = lib.types.attrsOf (lib.types.submodule { config.fprintAuth = lib.mkDefault false; });
  };

  options.aurora.sep.greeterFingerprint.enable = lib.mkOption {
    type = lib.types.bool;
    default = false;
    description = ''
      Offer fingerprint at the GNOME login screen as well as the lock screen.
      GNOME Shell only offers it on the lock screen, because a fingerprint
      login cannot unlock the keyring. The login screen also waits for Touch ID
      to come up, up to 90 s after boot.
    '';
  };

  config = lib.mkMerge [
    {
      # Explicit service loading waits for /var and per-machine firmware. This only
      # suppresses early alias loading; the boot timer enables SEP on the real root.
      boot.blacklistedKernelModules = [ "apple_sep" ];
      environment.systemPackages = [ pkgs.aurora-sep pkgs.libfprint ];
      services.fprintd.enable = true;
      # Touch ID: a fingerprint or the password at sudo, polkit and the lock
      # screens (gdm-fingerprint, and kde-fingerprint from the Plasma module);
      # the password at the login screens, the console login, su and ssh.
      # fprintAuth puts pam_fprintd in as "sufficient", ahead of the password.
      security.pam.services = {
        sudo.fprintAuth = true;
        polkit-1.fprintAuth = true;
        login.fprintAuth = false;
        su.fprintAuth = false;
        sshd = lib.mkIf config.services.openssh.enable { fprintAuth = false; };
      };
      # The Touch ID sensor is the power button: a short press suspends and a
      # 5 s press powers off wherever no desktop handles the button. In Plasma
      # PowerDevil handles it; powerdevilrc makes its short press suspend too.
      services.logind.settings.Login = {
        HandlePowerKey = lib.mkDefault "suspend";
        HandlePowerKeyLongPress = lib.mkDefault "poweroff";
      };
      environment.etc."xdg/powerdevilrc" = lib.mkIf config.services.desktopManager.plasma6.enable {
        source = ../sep/powerdevilrc;
      };
      systemd.timers.aurora-sep = {
        description = "Initialize Aurora SEP after persistent storage is available";
        wantedBy = [ "timers.target" ];
        timerConfig.OnBootSec = "1";
        timerConfig.Unit = "aurora-sep.service";
      };
      systemd.services.aurora-sep = {
        description = "Aurora SEP trusted keys and biometric services";
        after = [ "local-fs.target" "aurora-vendor-firmware.service" ];
        wants = [ "aurora-vendor-firmware.service" "aurora-sep-ready.service" "aurora-touchid-setup.service" ];
        unitConfig = {
          RequiresMountsFor = "/var/lib";
          ConditionPathExists = "/dev/disk/by-partlabel/iBootSystemContainer";
        };
        path = [ pkgs.kmod pkgs.gnugrep ];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          ExecCondition = "${pkgs.runtimeShell} -c 'modinfo -F filename apple_sep 2>/dev/null | grep -Eq \"[.]ko([.](gz|xz|zst))?$\"'";
          # Links the Touch ID files kept in /var/lib into the firmware path
          # on /run; it builds nothing.
          ExecStartPre = "-${pkgs.aurora-sep}/libexec/aurora/touchid-publish";
          ExecStart = "${pkgs.aurora-sep}/libexec/aurora-sep-load";
          StateDirectory = "aurora-sep";
          StateDirectoryMode = "0700";
          TimeoutStartSec = 180;
        };
      };
      systemd.services.aurora-touchid-setup = {
        description = "Set up the Touch ID calibration when it is missing or refused";
        documentation = [ "file://${pkgs.aurora-sep}/share/doc/aurora-sep/README.md" ];
        after = [ "local-fs.target" "aurora-vendor-firmware.service" ];
        before = [ "aurora-sep-ready.service" "fprintd.service" ];
        unitConfig = {
          RequiresMountsFor = "/var/lib";
          ConditionPathExists = "/dev/disk/by-partlabel/iBootSystemContainer";
        };
        serviceConfig = {
          Type = "oneshot";
          # Runs only when a Touch ID file is missing, when the enclave refused
          # one this boot (aurora-sep-ready starts this unit then), or on the
          # first boot after installation. Every other boot skips it here.
          ExecCondition = "${pkgs.aurora-sep}/libexec/aurora/touchid-setup-needed";
          ExecStart = "${pkgs.aurora-sep}/bin/aurora-touchid-setup --auto";
          TimeoutStartSec = 300;
        };
      };
      systemd.services.aurora-sep-ready = {
        description = "Activate Touch ID and restore its fingerprints";
        documentation = [ "file://${pkgs.aurora-sep}/share/doc/aurora-sep/README.md" ];
        requires = [ "aurora-sep.service" ];
        after = [ "aurora-sep.service" ];
        before = [ "fprintd.service" ];
        unitConfig = {
          ConditionPathExists = "/dev/sep-bio";
          # Whatever is ordered after this waits for the enclave, which can take
          # most of a minute after boot; stop waiting 90 s after boot.
          JobTimeoutSec = 90;
        };
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          ExecCondition = "${pkgs.aurora-sep}/libexec/aurora/sensor-present";
          ExecStart = "${pkgs.aurora-sep}/libexec/aurora-sep-ready";
          # The script gives up after 50 s and fails the unit when Touch ID is
          # not ready; this only catches a hung open.
          TimeoutStartSec = 60;
        };
      };
      systemd.services.fprintd = {
        requires = [ "aurora-sep.service" ];
        after = [ "aurora-sep.service" "aurora-sep-ready.service" ];
        unitConfig.ConditionPathExists = "/dev/sep-bio";
        serviceConfig = {
          ExecCondition = "${pkgs.aurora-sep}/libexec/aurora/sensor-present";
          DeviceAllow = [ "/dev/sep-bio rw" "char-input r" ];
          # Keep fprintd running instead of exiting after 30 s without a client,
          # so the login and lock screens find the reader at once.
          ExecStart = [ "" "${config.services.fprintd.package}/libexec/fprintd --no-timeout" ];
        };
      };
    }
    (lib.mkIf cfg.greeterFingerprint.enable {
      systemd.services.aurora-sep-greeter-fingerprint = {
        description = "Offer fingerprint at the GNOME login screen";
        documentation = [ "file://${pkgs.aurora-sep}/share/doc/aurora-sep/README.md" ];
        # The login screen asks fprintd for the reader once, as it comes up.
        wants = [ "aurora-sep-ready.service" ];
        after = [ "aurora-sep-ready.service" ];
        before = [ "display-manager.service" ];
        wantedBy = [ "display-manager.service" ];
        path = [ pkgs.coreutils pkgs.gnugrep pkgs.gawk pkgs.glib.dev ];
        environment.AURORA_SEP_GNOME_SHELL = "${pkgs.gnome-shell}";
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          ExecStart = "${pkgs.aurora-sep}/libexec/aurora-sep-greeter-fingerprint";
          ExecStop = "${pkgs.aurora-sep}/libexec/aurora-sep-greeter-fingerprint stop";
        };
      };
    })
  ];
}
