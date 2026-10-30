{ config, lib, pkgs, ... }:
let
  layout = config.aurora.imageLayout;
  layoutFile = pkgs.writeText "aurora-image-layout" ''
    format=1
    root_uuid=${layout.rootUUID}
    boot_uuid=${layout.bootUUID}
    root_subvolume=root
  '';
  xkb = config.services.xserver.xkb;
in {
  options.aurora.firstboot.passwordHooks = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = ''
      Declare the first-boot PAM hooks that let the owner's first password
      sign-in become the disk password. aurora-firstboot sets this to false in
      /etc/nixos/owner.nix once the password unlocks the disk, so the next
      rebuild removes the hooks; until then they do nothing.
    '';
  };
  options.aurora.imageLayout = lib.mkOption {
    default = null;
    description = "Filesystem identities sealed into an Aurora installer image.";
    type = lib.types.nullOr (lib.types.submodule {
      options = {
        rootUUID = lib.mkOption { type = lib.types.strMatching "[a-f0-9-]{36}"; };
        bootUUID = lib.mkOption { type = lib.types.strMatching "[a-f0-9-]{36}"; };
        efiUUID = lib.mkOption { type = lib.types.strMatching "[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}"; };
      };
    });
  };
  config = lib.mkIf (layout != null) {
    environment.systemPackages = [ pkgs.aurora-firstboot ];
    environment.etc."aurora/image-layout".source = layoutFile;
    # These identities persist in machine.nix across nixos-rebuild generations.
    fileSystems."/".device = lib.mkForce "/dev/disk/by-uuid/${layout.rootUUID}";
    fileSystems."/home".device = lib.mkForce "/dev/disk/by-uuid/${layout.rootUUID}";
    fileSystems."/boot".device = lib.mkForce "/dev/disk/by-uuid/${layout.bootUUID}";
    fileSystems."/boot/efi".device = lib.mkForce "/dev/disk/by-uuid/${layout.efiUUID}";
    boot.initrd.systemd.storePaths = [ pkgs.aurora-firstboot ] ++ pkgs.aurora-firstboot.initrdInputs;
    # GRUB must never probe other disks or NVMe namespaces (probing them can
    # wedge U-Boot), and a core image grub-install builds on this layout names
    # a fixed partition slot. After every bootloader install, rebuild the core
    # so its EFI stub finds /boot by UUID on the startup disk only.
    # pkgs.grub2_efi is what the bootloader module installs (no ZFS support here).
    boot.loader.grub.extraInstallCommands = let
      grubEfi = pkgs.grub2_efi;
    in ''
      ${pkgs.python3.interpreter} ${pkgs.aurora-firstboot}/lib/aurora/aurora-harden-grub / --flavor arch \
        --boot-uuid ${layout.bootUUID} --efi-uuid ${layout.efiUUID} \
        --grub-mkimage ${grubEfi}/bin/grub-mkimage --grub-modules ${grubEfi}/lib/grub/arm64-efi
    '';
    boot.initrd.systemd.contents."/etc/aurora/image-layout".source = layoutFile;
    # Take over any watchdog still running at handoff before a long in-place
    # encryption pass can outlast its timeout.
    boot.initrd.kernelModules = [ "apple_wdt" "dm-crypt" "btrfs" "ext4" "vfat" ];
    boot.initrd.systemd.services.aurora-initrd-root = {
      description = "Prepare and unlock the Aurora root filesystem";
      wantedBy = [ "initrd.target" ];
      wants = [ "systemd-udev-settle.service" ];
      # The unlock prompt reads the disk password with the console keymap.
      after = [ "systemd-udev-settle.service" "aurora-vendor-firmware.service" "plymouth-start.service"
        "systemd-vconsole-setup.service" ];
      before = [ "sysroot.mount" "cryptsetup-pre.target" "initrd-root-device.target" ];
      unitConfig.DefaultDependencies = false;
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        TimeoutStartSec = "infinity";
        ExecStartPre = "${pkgs.kmod}/bin/modprobe apple_wdt";
        ExecStart = "${pkgs.aurora-firstboot}/lib/aurora/aurora-initrd-root";
        Environment = "AURORA_IMAGE_LAYOUT=${layoutFile}";
      };
    };
    boot.initrd.systemd.units."sysroot.mount" = {
      overrideStrategy = "asDropin";
      # The first conversion replaces the plaintext device while the initrd
      # is running. Queue sysroot against the mapper from the outset so its
      # original device job cannot expire during the conversion.
      text = ''
        [Unit]
        Requires=aurora-initrd-root.service
        After=aurora-initrd-root.service

        [Mount]
        What=/dev/mapper/root
      '';
    };
    boot.initrd.systemd.units."dev-mapper-root.device" = {
      overrideStrategy = "asDropin";
      # The first-boot LUKS conversion can take longer than systemd's default
      # device-job timeout. Keep waiting for the mapper while the conversion
      # service runs; its own failures are reported by that service.
      text = ''
        [Unit]
        JobRunningTimeoutSec=infinity
      '';
    };
    # The shared aurora-firstboot.service, declared here because the package
    # carries no unit files. On desktop images the desktop's own setup creates
    # the owner (Plasma Setup on KDE, GNOME Initial Setup on GNOME), whose
    # password then also protects the disk. Minimal images and
    # any boot with aurora.firstboot=text use the text wizard on tty1, which
    # creates the owner itself; that option also starts it for recovery while
    # setup is no longer pending but no owner exists.
    systemd.services.aurora-firstboot = {
      description = "Aurora first-boot setup";
      wantedBy = [ "multi-user.target" ];
      # Plymouth must have started before setup uses or releases it.
      after = [ "local-fs.target" "systemd-user-sessions.service" "systemd-vconsole-setup.service" "plymouth-start.service" ];
      before = [ "display-manager.service" "getty@tty1.service" ];
      unitConfig.RequiresMountsFor = [ "/boot" "/boot/efi" "/home" ];
      unitConfig.ConditionPathExists = "|/var/lib/aurora/firstboot/pending";
      unitConfig.ConditionKernelCommandLine = "|aurora.firstboot=text";
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        TimeoutStartSec = "infinity";
        ExecStart = "${pkgs.aurora-firstboot}/lib/aurora/aurora-firstboot";
        # The unit never takes tty1: Plymouth reads the splash password
        # prompt's keystrokes from it. The text wizard opens tty1 itself once
        # the splash is gone.
        StandardInput = "null"; StandardOutput = "journal"; StandardError = "journal";
      };
    };
    # The owner's password, at its first sign-in, also becomes the disk
    # password (aurora-firstboot); first boot asks nothing on the splash,
    # which stops updating on the MacBook Neo once the system has started.
    # NixOS generates /etc/pam.d, so the hooks are declared here. While the
    # disk opens with its temporary key, the gate holds the new owner's
    # automatic login (Plasma Setup's) so the greeter asks for the password
    # once. After the rekey they return at once (the disk-rekeyed marker), and
    # the rekey sets aurora.firstboot.passwordHooks = false in owner.nix, so
    # the next rebuild removes them.
    environment.etc."aurora/password-hooks" = lib.mkIf config.aurora.firstboot.passwordHooks {
      text = "sddm sddm-autologin gdm-password\n";
    };
    security.pam.services = lib.mkIf config.aurora.firstboot.passwordHooks (let
      pamExec = "${config.security.pam.package}/lib/security/pam_exec.so";
      hook = "${pkgs.aurora-firstboot}/lib/aurora/aurora-password-hook";
      signIn = {
        order = 0;
        control = "optional";
        modulePath = pamExec;
        args = [ "quiet" "expose_authtok" hook ];
      };
    in lib.mkMerge [
      (lib.mkIf config.services.displayManager.sddm.enable {
        sddm.rules.auth.aurora-password-hook = signIn;
        sddm-autologin.rules.auth.aurora-password-gate = {
          order = 0;
          control = "requisite";
          modulePath = pamExec;
          args = [ "quiet" hook "--gate" ];
        };
      })
      (lib.mkIf config.services.displayManager.gdm.enable {
        gdm-password.rules.auth.aurora-password-hook = signIn;
      })
    ]);
    # The disk password is typed at the initrd prompt with console.keyMap and
    # at the greeter with the XKB layout. Derive the console keymap from the
    # XKB settings, as console.useXkbConfig does, but with mkDefault priority:
    # an explicit console.keyMap or console.useXkbConfig still wins.
    console.keyMap = lib.mkIf (xkb.layout != "us" || xkb.variant != "") (lib.mkDefault
      (pkgs.runCommand "xkb-console-keymap" { preferLocalBuild = true; } ''
        '${pkgs.buildPackages.ckbcomp}/bin/ckbcomp' \
          ${lib.optionalString (config.environment.sessionVariables ? XKB_CONFIG_ROOT)
            "-I${config.environment.sessionVariables.XKB_CONFIG_ROOT}"} \
          -model '${xkb.model}' -layout '${xkb.layout}' \
          -option '${xkb.options}' -variant '${xkb.variant}' > "$out"
      ''));
    # NixOS's localed is read-only and writes no 00-keyboard.conf: tell
    # aurora-firstboot which layout the greeter uses, so the rekey can compare
    # it with the console keymap.
    environment.etc."aurora/keyboard".text = ''
      layout=${xkb.layout}
      variant=${xkb.variant}
    '';
    systemd.services.aurora-disk-rekey = {
      description = "Let the Aurora owner password unlock the disk";
      unitConfig.ConditionPathExists = "/run/aurora-firstboot/password";
      unitConfig.RequiresMountsFor = [ "/boot" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${pkgs.aurora-firstboot}/lib/aurora/aurora-firstboot --rekey";
        StandardOutput = "journal";
        StandardError = "journal";
      };
    };
    # The shared plymouth-quit.service drop-in: the splash stays up until
    # first-boot setup has finished, with any display manager.
    systemd.services.plymouth-quit = lib.mkIf config.boot.plymouth.enable {
      after = [ "aurora-firstboot.service" ];
    };
    # The shared plasma-setup.service drop-in: Plasma Setup waits until the
    # disk is protected, and is skipped, never failed, while setup is pending
    # and when the text wizard created the owner.
    systemd.services.plasma-setup = lib.mkIf config.aurora.plasmaSetup.enable {
      after = [ "aurora-firstboot.service" ];
      unitConfig.ConditionPathExists = [ "!/var/lib/aurora/firstboot/pending" "!/var/lib/aurora/firstboot/complete" ];
    };
    # Until the owner performs the first rebuild, the factory generation still
    # contains its generic hostname. Restore the chosen name after activation.
    # Once owner.nix is built, its normal user declaration removes this bridge.
    systemd.services.aurora-owner-hostname = lib.mkIf
      (lib.filterAttrs (_: user: user.isNormalUser) config.users.users == {}) {
      description = "Restore the Aurora owner's hostname before the first rebuild";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-pre.target" ];
      after = [ "local-fs.target" ];
      before = [ "network-pre.target" "NetworkManager.service" "systemd-hostnamed.service" ];
      unitConfig.ConditionPathExists = "/var/lib/aurora/firstboot/complete";
      serviceConfig.Type = "oneshot";
      path = [ pkgs.coreutils ];
      script = ''
        state=/var/lib/aurora/firstboot
        [[ -f $state/owner && ! -L $state/owner ]] || exit 1
        mapfile -t owner < "$state/owner"
        (( ''${#owner[@]} == 2 )) || exit 1
        [[ $(<"$state/complete") == "''${owner[0]}" ]] || exit 1
        hostname=''${owner[1]}
        [[ $hostname =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$ ]] || exit 1
        printf '%s\n' "$hostname" > /etc/hostname.aurora-new
        chmod 0644 /etc/hostname.aurora-new
        mv -Tf /etc/hostname.aurora-new /etc/hostname
        printf '%s\n' "$hostname" > /proc/sys/kernel/hostname
      '';
    };
    # NixOS normally directs hostnamed to its immutable generation's hostname.
    # The factory generation must instead read the owner-updated /etc file.
    systemd.services.systemd-hostnamed = lib.mkIf
      (lib.filterAttrs (_: user: user.isNormalUser) config.users.users == {}) {
      environment.SYSTEMD_ETC_HOSTNAME = lib.mkForce "/etc/hostname";
    };
    systemd.services.display-manager = lib.mkIf (config.aurora.desktop != "minimal") {
      after = [ "aurora-firstboot.service" ];
      # On the first boot, wait for account setup and its final state write.
      # A completed setup is skipped on later boots, but the greeter must still start.
      unitConfig.ConditionPathExists = "!/var/lib/aurora/firstboot/pending";
    };
    systemd.services."getty@" = {
      overrideStrategy = "asDropin";
      unitConfig.ConditionPathExists = "!/var/lib/aurora/firstboot/pending";
      after = [ "aurora-firstboot.service" ];
    };
    systemd.services."serial-getty@" = {
      overrideStrategy = "asDropin";
      unitConfig.ConditionPathExists = "!/var/lib/aurora/firstboot/pending";
      after = [ "aurora-firstboot.service" ];
    };
  };
}
