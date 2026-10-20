{ config, lib, pkgs, ... }:
let
  admission = pkgs.runCommand "aurora-peripheral-admission" { } ''
    install -Dm755 ${../firmware/aurora-peripheral-firmware.sh} $out/bin/aurora-peripheral-admission
    patchShebangs $out/bin/aurora-peripheral-admission
  '';
  firmwareTools = [ pkgs.coreutils pkgs.util-linux pkgs.cpio pkgs.kmod pkgs.gnugrep pkgs.bash pkgs.systemd ];
  loadFirmware = pkgs.writeShellApplication {
    name = "aurora-load-vendor-firmware";
    runtimeInputs = firmwareTools;
    text = ''
      property=/sys/firmware/devicetree/base/chosen/asahi,efi-system-partition
      if [ ! -r "$property" ]; then exit 0; fi
      uuid=$(tr -d '\000' < "$property")
      [[ "$uuid" =~ ^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$ ]] || {
        echo 'Invalid Apple EFI partition identity' >&2; exit 1;
      }
      uuid=''${uuid,,}
      destination=/run/aurora-firmware
      mkdir -p "$destination" /run/aurora-esp
      if [ ! -s "$destination/vendorfw/.vendorfw.manifest" ]; then
        udevadm wait --timeout=60 "/dev/disk/by-partuuid/$uuid"
        mount -t vfat -o ro "/dev/disk/by-partuuid/$uuid" /run/aurora-esp
        trap 'umount /run/aurora-esp' EXIT
        test -s /run/aurora-esp/vendorfw/firmware.cpio
        (cd "$destination"; cpio --quiet --extract --no-absolute-filenames < /run/aurora-esp/vendorfw/firmware.cpio)
      fi
      export AURORA_FIRMWARE_ROOT="$destination/vendorfw"
      export AURORA_ADMIT_BLUETOOTH=0
      if [[ "''${1:-initrd}" == runtime ]]; then
        export AURORA_ADMIT_BLUETOOTH=1
      fi
      ${admission}/bin/aurora-peripheral-admission
    '';
  };
in {
  # The distributable image cannot embed another Mac's calibration in /nix/store.
  # Replace build-time extraction with an initrd/runtime ESP handoff.
  hardware.asahi.extractPeripheralFirmware = lib.mkDefault false;
  boot.kernelParams = [ "firmware_class.path=/run/aurora-firmware/vendorfw" ];
  # Neo input must probe after the ESP firmware reaches the initrd runtime.
  boot.blacklistedKernelModules = [ "aop" "mt7932-fullmac" "mt7932_bt_pcie" "dockchannel-hid" ];
  boot.initrd.availableKernelModules = [ "vfat" "nvme_apple" "apple-mailbox" "aop" "mt7932-fullmac" "mt7932_bt_pcie" ];
  boot.initrd.systemd.services.aurora-vendor-firmware = lib.mkIf config.boot.initrd.systemd.enable {
    description = "Extract this Mac's vendor firmware before peripheral admission";
    wantedBy = [ "initrd.target" ];
    after = [ "systemd-udev-settle.service" ];
    wants = [ "systemd-udev-settle.service" ];
    before = [ "sysroot.mount" "cryptsetup-pre.target" "aurora-initrd-root.service" ];
    serviceConfig.Type = "oneshot";
    serviceConfig.ExecStart = "${loadFirmware}/bin/aurora-load-vendor-firmware";
  };
  boot.initrd.systemd.storePaths = lib.mkIf config.boot.initrd.systemd.enable ([ loadFirmware admission ] ++ map lib.getBin firmwareTools);
  systemd.services.aurora-vendor-firmware = {
    description = "Maintain Aurora per-device firmware handoff";
    wantedBy = [ "multi-user.target" ];
    after = [ "local-fs.target" ];
    before = [ "bluetooth.service" ];
    serviceConfig.Type = "oneshot";
    serviceConfig.RemainAfterExit = true;
    serviceConfig.ExecStart = "${loadFirmware}/bin/aurora-load-vendor-firmware runtime";
  };
  # Use the same service-based early boot as Fedora to preserve firmware order.
  boot.initrd.systemd.enable = lib.mkDefault true;
}
