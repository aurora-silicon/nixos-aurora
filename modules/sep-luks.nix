{ config, lib, pkgs, ... }:
let
  cfg = config.aurora.sepLuks;
  plugins = "${cfg.package}/lib/cryptsetup";
  initrdLoad = "${cfg.package}/lib/aurora-sep/initrd/aurora-sep-initrd-load";
  # keystore_only=2 also unlocks per-user key bags in the initrd, for volumes
  # sealed to a user's password (aurora-sep-fde).
  keystoreOnly = if cfg.initrd.passwordUnlock then "2" else "1";
  pamModules = "${config.security.pam.package}/lib/security";
  # After pam_unix changed the password, and only then:
  #
  #   password [success=ok default=2] pam_unix.so ...
  #   password optional   pam_aurora_sep_fde.so helper=...
  #   password sufficient pam_permit.so
  #   password required   pam_deny.so
  #
  # pam_unix's failure jumps onto pam_deny, so the disk password is never
  # changed for a password change that failed.
  passwordRules = name: let unix = config.security.pam.services.${name}.rules.password.unix; in {
    unix.control = lib.mkForce "[success=ok default=2]";
    aurora_sep_fde = {
      order = unix.order + 10;
      control = "optional";
      modulePath = "${cfg.package}/lib/security/pam_aurora_sep_fde.so";
      args = [ "helper=${cfg.package}/libexec/aurora-sep-fde-passwd" ];
    };
    aurora_sep_fde_done = {
      order = unix.order + 20;
      control = "sufficient";
      modulePath = "${pamModules}/pam_permit.so";
    };
    aurora_sep_fde_unix_failed = {
      order = unix.order + 30;
      control = "required";
      modulePath = "${pamModules}/pam_deny.so";
    };
  };
in {
  options.aurora.sepLuks = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Install aurora-sep-cryptenroll, aurora-sep-fde and the libcryptsetup
        token plugin, which unlock LUKS2 volumes with this Mac's Secure Enclave.
        aurora-sep-cryptenroll seals a volume to the Mac, the way
        systemd-cryptenroll --tpm2-device=auto does with a TPM. aurora-sep-fde
        seals it to users' passwords, checked by the Secure Enclave (the
        FileVault model): each user gets their own keyslot, and volume owners
        add, remove and reset users. Nothing is enrolled by this option: run
        either tool for each volume. /etc/aurora-sep/fde.conf comes from the
        package unless environment.etc."aurora-sep/fde.conf" is set.
      '';
    };
    initrd.enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Open Secure Enclave volumes in the initrd too, the root volume included.
        Needs a kernel whose apple_sep has the
        key-store-only attach phase (the keystore_only parameter); with an
        older kernel the initrd leaves the driver alone and those volumes ask
        for their passphrase. For volumes sealed by aurora-sep-cryptenroll the
        SEP key store files from /var/lib go into the initrd through
        boot.initrd.secrets (never the Nix store), so they must exist when the
        boot loader is installed: enable Touch ID or run the SEP once first.
        Rebuild after the key store changes. Every volume keeps its passphrase
        or recovery key.
      '';
    };
    initrd.passwordUnlock = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Also open volumes sealed to a user's password by aurora-sep-fde in the
        initrd: apple_sep loads there with keystore_only=2, which unlocks the
        user's key bag with the password typed at the prompt. Needs a kernel
        whose keystore_only parameter offers per-user key bags. Those tokens
        carry their wrapped key bag in the LUKS2 header, so this mode needs no
        key store copies.
      '';
    };
    initrd.keyStore = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Copy the SEP key store (/var/lib/aurora-sep-keybag.bin and
        /var/lib/aurora-sep-refkey.bin) into the initrd as boot.initrd.secrets,
        for volumes sealed by aurora-sep-cryptenroll. Turn it off on a system
        whose initrd volumes are all sealed to passwords
        (initrd.passwordUnlock) and that has no key store yet.
      '';
    };
    passwordSync = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = cfg.enable;
        defaultText = lib.literalExpression "config.aurora.sepLuks.enable";
        description = ''
          Keep a user's disk password equal to their login password: after
          pam_unix changed a password (passwd, GNOME Settings), the
          pam_aurora_sep_fde module re-wraps the user's key bag in the Secure
          Enclave and writes it to every volume listed in
          /etc/aurora-sep/fde-volumes. The password stacks of
          passwordSync.services run it after pam_unix, which becomes
          authoritative there: a failed pam_unix change fails the stack
          instead of falling through to later password modules. A change
          without the old password (root running passwd for another user,
          chpasswd) leaves the disk password as it was and says how a volume
          owner resets it.
        '';
      };
      services = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ "passwd" ];
        example = [ "passwd" "login" "gdm-password" ];
        description = ''
          PAM services whose password changes also change the disk password.
          passwd covers passwd and GNOME Settings; add the login services to
          follow a change of an expired password at login.
        '';
      };
    };
    package = lib.mkPackageOption pkgs "aurora-sep-luks" { };
  };

  config = lib.mkIf cfg.enable (lib.mkMerge [
    {
      environment.systemPackages = [ cfg.package ];
      environment.etc."aurora-sep/fde.conf".source = lib.mkDefault "${cfg.package}/etc/aurora-sep/fde.conf";
      # nixpkgs' cryptsetup loads token plugins by name through the library
      # search path (relative-token-path.patch), so point crypttab's
      # systemd-cryptsetup instances at the plugin.
      systemd.services."systemd-cryptsetup@" = {
        overrideStrategy = "asDropin";
        environment.LD_LIBRARY_PATH = plugins;
      };
    }
    (lib.mkIf cfg.passwordSync.enable {
      security.pam.services = lib.genAttrs cfg.passwordSync.services (name: {
        rules.password = passwordRules name;
      });
    })
    (lib.mkIf cfg.initrd.enable {
      # The initrd is systemd's (nixpkgs removed the scripted one), so
      # systemd-cryptsetup and its token plugins run there.
      assertions = [{
        assertion = cfg.initrd.keyStore || cfg.initrd.passwordUnlock;
        message = "aurora.sepLuks.initrd: without initrd.keyStore only password-sealed volumes can open there; set initrd.passwordUnlock.";
      }];
      # Loaded by aurora-sep-initrd below with keystore_only, never by alias.
      boot.initrd.availableKernelModules = [ "apple_sep" "algif_aead" "ccm" "ctr" ];
      boot.initrd.secrets = lib.mkIf cfg.initrd.keyStore {
        "/var/lib/aurora-sep-keybag.bin" = "/var/lib/aurora-sep-keybag.bin";
        "/var/lib/aurora-sep-refkey.bin" = "/var/lib/aurora-sep-refkey.bin";
      };
      # The token plugin and the loader (with its interpreter) by closure.
      boot.initrd.systemd.storePaths = [ plugins initrdLoad ];
      # What the loader reads: the keystore_only mode, as the dracut module and
      # the mkinitcpio hook write it.
      boot.initrd.systemd.contents."/usr/lib/aurora-sep/initrd.conf".text =
        "AURORA_SEP_KEYSTORE_ONLY=${keystoreOnly}\n";
      boot.initrd.systemd.services.aurora-sep-initrd = {
        description = "Secure Enclave key store for LUKS2 unlock";
        unitConfig = {
          DefaultDependencies = false;
          ConditionPathExists = [ "/usr/lib/aurora-sep/initrd.conf" ]
            # Machine-sealed tokens only: nothing to do without the key store.
            ++ lib.optional (!cfg.initrd.passwordUnlock) "/var/lib/aurora-sep-keybag.bin";
        };
        after = [ "systemd-modules-load.service" ];
        before = [ "cryptsetup-pre.target" ];
        wants = [ "cryptsetup-pre.target" ];
        wantedBy = [ "sysinit.target" "cryptsetup-pre.target" ];
        # modprobe and modinfo (kmod) are in the initrd's /bin.
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
