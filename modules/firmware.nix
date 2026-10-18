{ config, lib, pkgs, ... }:
let
  loadFirmware = pkgs.writeShellApplication {
    name = "aurora-load-vendor-firmware";
    runtimeInputs = [ pkgs.coreutils pkgs.util-linux pkgs.cpio pkgs.kmod pkgs.gnugrep ];
    text = ''
      property=/sys/firmware/devicetree/base/chosen/asahi,efi-system-partition
      if [ ! -r "$property" ]; then exit 0; fi
      uuid=$(tr -d '\000' < "$property")
      case "$uuid" in
        ????????-????-????-????-????????????) ;;
        *) echo 'Invalid Apple EFI partition identity' >&2; exit 1 ;;
      esac
      destination=/run/aurora-firmware
      mkdir -p "$destination" /run/aurora-esp
      if [ ! -s "$destination/vendorfw/.vendorfw.manifest" ]; then
        mount -t vfat -o ro "/dev/disk/by-partuuid/$uuid" /run/aurora-esp
        trap 'umount /run/aurora-esp' EXIT
        test -s /run/aurora-esp/vendorfw/firmware.cpio
        (cd "$destination"; cpio --quiet --extract --no-absolute-filenames < /run/aurora-esp/vendorfw/firmware.cpio)
      fi
      # Admit devices after their own Mac's firmware is available.
      modprobe aop || true
      if tr '\000' '\n' < /sys/firmware/devicetree/base/compatible | grep -qx apple,j700; then
        modprobe mt7932-fullmac
        modprobe mt7932_bt_pcie
      fi
    '';
  };
in {
  # The distributable image cannot embed another Mac's calibration in /nix/store.
  # Replace build-time extraction with an initrd/runtime ESP handoff.
  hardware.asahi.extractPeripheralFirmware = lib.mkDefault false;
  boot.kernelParams = [ "firmware_class.path=/run/aurora-firmware/vendorfw" ];
  boot.blacklistedKernelModules = [ "aop" "mt7932-fullmac" "mt7932_bt_pcie" ];
  boot.initrd.availableKernelModules = [ "vfat" "nvme_apple" "apple-mailbox" "aop" "mt7932-fullmac" "mt7932_bt_pcie" ];
  boot.initrd.systemd.services.aurora-vendor-firmware = lib.mkIf config.boot.initrd.systemd.enable {
    description = "Extract this Mac's vendor firmware before peripheral admission";
    wantedBy = [ "initrd.target" ];
    after = [ "systemd-udev-settle.service" ];
    wants = [ "systemd-udev-settle.service" ];
    before = [ "sysroot.mount" ];
    serviceConfig.Type = "oneshot";
    serviceConfig.ExecStart = "${loadFirmware}/bin/aurora-load-vendor-firmware";
  };
  boot.initrd.systemd.storePaths = lib.mkIf config.boot.initrd.systemd.enable [ loadFirmware ];
  systemd.services.aurora-vendor-firmware = {
    description = "Maintain Aurora per-device firmware handoff";
    wantedBy = [ "multi-user.target" ];
    after = [ "local-fs.target" ];
    serviceConfig.Type = "oneshot";
    serviceConfig.RemainAfterExit = true;
    serviceConfig.ExecStart = "${loadFirmware}/bin/aurora-load-vendor-firmware";
  };
  # Use the same service-based early boot as Fedora to preserve firmware order.
  boot.initrd.systemd.enable = lib.mkDefault true;
}
