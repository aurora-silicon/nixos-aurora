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
    boot.initrd.systemd.contents."/etc/aurora/image-layout".source = layoutFile;
    boot.initrd.kernelModules = [ "dm-crypt" "btrfs" "ext4" "vfat" ];
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
        ExecStart = "${pkgs.aurora-firstboot}/lib/aurora/aurora-initrd-root";
        Environment = "AURORA_IMAGE_LAYOUT=${layoutFile}";
      };
    };
    boot.initrd.systemd.units."sysroot.mount" = {
      overrideStrategy = "asDropin";
      text = ''
        [Unit]
        Requires=aurora-initrd-root.service
        After=aurora-initrd-root.service
      '';
    };
    systemd.services.aurora-firstboot = {
      description = "Create the Aurora Linux owner account";
      wantedBy = [ "multi-user.target" ];
      after = [ "local-fs.target" "systemd-user-sessions.service" "systemd-vconsole-setup.service" ];
      before = [ "display-manager.service" "getty@tty1.service" ];
      unitConfig.RequiresMountsFor = [ "/boot" "/boot/efi" "/home" ];
      unitConfig.ConditionPathExists = "/var/lib/aurora/firstboot/pending";
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        TimeoutStartSec = "infinity";
        ExecStart = "${pkgs.aurora-firstboot}/lib/aurora/aurora-firstboot";
        StandardInput = "tty"; StandardOutput = "tty"; StandardError = "tty";
        TTYPath = "/dev/tty1"; TTYReset = true; TTYVHangup = true;
      };
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
      requires = [ "aurora-firstboot.service" ];
      after = [ "aurora-firstboot.service" ];
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
