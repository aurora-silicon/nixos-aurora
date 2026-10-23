{ config, lib, pkgs, ... }:
let
  layout = config.aurora.imageLayout;
  layoutFile = pkgs.writeText "aurora-image-layout" ''
    format=1
    root_uuid=${layout.rootUUID}
    boot_uuid=${layout.bootUUID}
    root_subvolume=root
  '';
in {
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
      after = [ "systemd-udev-settle.service" "aurora-vendor-firmware.service" "plymouth-start.service" ];
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
    # carries no unit files. Desktop images protect the disk with a password
    # asked on the boot splash, then the desktop's own setup creates the owner
    # (Plasma Setup on KDE, GNOME Initial Setup on GNOME). Minimal images and
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
    # The shared plymouth-quit.service drop-in: the splash stays up for the
    # disk password prompt with any display manager.
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
