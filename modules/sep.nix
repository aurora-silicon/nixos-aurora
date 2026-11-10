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
      Patch GNOME Shell's greeter to offer fingerprint sign-in as well as
      lock-screen authentication. The greeter waits for Touch ID readiness,
      up to 90 seconds after boot; fingerprint sign-in does not unlock the
      keyring. False leaves the normal password greeter and keeps lock-screen,
      sudo and polkit fingerprint authentication enabled.
    '';
  };

  options.aurora.sep.requirePasswordAfterBoot = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = ''
      Touch ID after a restart. On (the default): as on macOS, the first login
      or unlock after boot needs the password ("Your password is required to
      enable Touch ID."), and Touch ID works after that password. Off: Touch ID
      works from the first login after boot. Written
      to /etc/aurora/touchid.conf (require_password_after_boot) and applied
      by aurora-touchid-boot.service at every boot.
    '';
  };

  config = lib.mkMerge [
    {
      # Explicit service loading waits for /var and per-machine firmware. This only
      # suppresses early alias loading; the boot timer enables SEP on the real root.
      boot.blacklistedKernelModules = [ "apple_sep" ];
      # The driver's defaults. Named to sort before aurora-sep.conf and
      # nixos.conf, so a read-only setting in either comes later and wins.
      environment.etc."modprobe.d/aurora-sep-defaults.conf".source = ../sep/aurora-sep-modprobe.conf;
      # aurora-xart reset-touchid starts Touch ID over when its keybag is stuck.
      # aurora-sep-sk: OpenSSH ecdsa-sk keys in the Secure Enclave for members
      # of sep-key (its udev rule gives that group /dev/sep-key).
      environment.systemPackages = [ pkgs.aurora-sep pkgs.aurora-xart pkgs.libfprint pkgs.aurora-sep-sk ];
      services.udev.packages = [ pkgs.aurora-sep-sk ];
      users.groups.sep-key = { };
      services.fprintd.enable = true;
      # Touch ID: a fingerprint or the password at sudo, polkit and the lock
      # screens (gdm-fingerprint, and kde-fingerprint from the Plasma module);
      # the password at the login screens, the console login, su and ssh.
      # fprintAuth puts pam_fprintd in as "sufficient", ahead of the password.
      # A password re-arms Touch ID after a lockout. pam_aurora_touchid runs
      # straight after a pam_unix success, and pam_permit then ends the stack
      # as "sufficient pam_unix" did; a failure jumps over both. Both lines
      # exist only where pam_unix does.
      security.pam.services = lib.mkMerge [
        (lib.genAttrs ([ "sudo" "polkit-1" "login" ]
          ++ lib.optional config.services.desktopManager.plasma6.enable "kde") (name:
          let unix = config.security.pam.services.${name}.rules.auth.unix; in {
            rules.auth = {
              unix.control = lib.mkForce "[success=ok new_authtok_reqd=ok default=2]";
              aurora-touchid-rearm = {
                inherit (unix) enable;
                order = unix.order + 1;
                control = "optional";
                modulePath = "${pkgs.aurora-touchid-rearm}/lib/security/pam_aurora_touchid.so";
              };
              aurora-touchid-rearm-done = {
                inherit (unix) enable;
                order = unix.order + 2;
                control = "sufficient";
                modulePath = "${pkgs.pam}/lib/security/pam_permit.so";
              };
            };
          }))
        {
          # aurora-touchid-rearm checks the password once more here.
          aurora-touchid-rearm.text = ''
            auth required ${pkgs.pam}/lib/security/pam_unix.so
            account required ${pkgs.pam}/lib/security/pam_unix.so
          '';
        }
        {
          sudo.fprintAuth = true;
          polkit-1.fprintAuth = true;
          login.fprintAuth = false;
          su.fprintAuth = false;
          sshd = lib.mkIf config.services.openssh.enable { fprintAuth = false; };
        }
      ];
      systemd.sockets.aurora-touchid-rearm = {
        description = "Touch ID re-arm after a password authentication";
        wantedBy = [ "sockets.target" ];
        socketConfig = {
          ListenStream = "/run/aurora-touchid-rearm.sock";
          SocketMode = "0666";
          Accept = true;
          MaxConnections = 8;
        };
      };
      environment.etc."aurora/touchid.conf".text = ''
        # Generated from aurora.sep.requirePasswordAfterBoot.
        require_password_after_boot = ${if cfg.requirePasswordAfterBoot then "yes" else "no"}
      '';
      # Before fprintd, through which every login, unlock and sudo reaches the
      # reader: with the setting on, the driver refuses Touch ID until the
      # first password since boot. The display manager does not wait for it.
      systemd.services.aurora-touchid-boot = {
        description = "Touch ID after a restart (require_password_after_boot)";
        wantedBy = [ "multi-user.target" ];
        wants = [ "aurora-sep-ready.service" ];
        after = [ "aurora-sep-ready.service" ];
        before = [ "fprintd.service" ];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          ExecStart = "${pkgs.aurora-touchid-rearm}/libexec/aurora-touchid-rearm --boot";
          StandardOutput = "null";
          TimeoutStartSec = 45;
          CapabilityBoundingSet = [ "CAP_SYS_ADMIN" ];
          NoNewPrivileges = true;
          PrivateNetwork = true;
          RestrictAddressFamilies = [ "AF_UNIX" ];
          ProtectSystem = "strict";
          ProtectHome = true;
          PrivateTmp = true;
          ProtectKernelTunables = true;
          ProtectKernelModules = true;
          ProtectControlGroups = true;
          LockPersonality = true;
          RestrictRealtime = true;
          RestrictNamespaces = true;
          SystemCallArchitectures = "native";
        };
      };
      systemd.services."aurora-touchid-rearm@" = {
        description = "Touch ID re-arm request";
        serviceConfig = {
          ExecStart = "${pkgs.aurora-touchid-rearm}/libexec/aurora-touchid-rearm";
          StandardInput = "socket";
          StandardOutput = "socket";
          StandardError = "journal";
          RuntimeMaxSec = 30;
          CapabilityBoundingSet = [ "CAP_SYS_ADMIN" "CAP_DAC_READ_SEARCH" "CAP_AUDIT_WRITE" ];
          NoNewPrivileges = true;
          PrivateNetwork = true;
          RestrictAddressFamilies = [ "AF_UNIX" "AF_NETLINK" ];
          ProtectSystem = "full";
          ProtectHome = true;
          PrivateTmp = true;
          ProtectKernelTunables = true;
          ProtectKernelModules = true;
          ProtectControlGroups = true;
          LockPersonality = true;
          RestrictRealtime = true;
          RestrictNamespaces = true;
          SystemCallArchitectures = "native";
        };
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
      # One mem request; preserve explicit kernel/user mode selection.
      # mkDefault leaves owner settings authoritative. MemorySleepMode was
      # introduced in systemd 256; older packages need only SuspendState.
      systemd.sleep.settings.Sleep = {
        SuspendState = lib.mkDefault "mem";
      } // lib.optionalAttrs (lib.versionAtLeast config.systemd.package.version "256") {
        MemorySleepMode = lib.mkDefault "";
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
      # Every sleep that suspends waits for a SEP load still in progress
      # (see the file). A drop-in only, also where a unit isn't shipped.
      systemd.units = lib.genAttrs [
        "systemd-suspend.service"
        "systemd-hybrid-sleep.service"
        "systemd-suspend-then-hibernate.service"
      ] (_: {
        overrideStrategy = "asDropin";
        text = builtins.readFile ../sep/sleep-aurora-sep.conf;
      });
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
