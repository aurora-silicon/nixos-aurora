{ config, lib, pkgs, ... }:
let
  tools = import ../firmware/package.nix { inherit pkgs; };
  inherit (tools) admission extractFirmware loadFirmware firmwareTools;
in {
  # The distributable image cannot embed another Mac's calibration in /nix/store.
  # Replace build-time extraction with an initrd/runtime ESP handoff.
  hardware.asahi.extractPeripheralFirmware = lib.mkDefault false;
  boot.kernelParams = [ "firmware_class.path=/run/aurora-firmware/vendorfw" ];
  # udev activation resets firmware_class.path on every switch, including
  # switches that leave our active oneshot unit unchanged. Restore the path
  # after that activation without rerunning extraction or peripheral probes.
  system.activationScripts.auroraFirmwarePath = lib.mkIf config.boot.kernel.enable {
    deps = [ "udevd" ];
    text = ''
      ${pkgs.runtimeShell} ${../firmware/restore-search-path.sh}
    '';
  };
  # The keyboard driver probes from the admission script, after the ESP
  # firmware reaches the initrd, so it is in the initrd but not autoloaded.
  # Broadcom radios and the ALS must wait for the real-root firmware path.
  # Some ALS probes without calibration succeed but never produce samples.
  boot.blacklistedKernelModules = [
    "aop" "mt7932-fullmac" "mt7932_bt_pcie" "dockchannel-hid"
    "brcmfmac" "hci_bcm4377" "aop_als"
  ];
  boot.initrd.availableKernelModules = [ "vfat" "nvme_apple" "apple-mailbox" "aop" "mt7932-fullmac" "mt7932_bt_pcie" "dockchannel-hid" ];
  boot.initrd.systemd.services.aurora-vendor-firmware = {
    description = "Extract this Mac's vendor firmware before peripheral admission";
    wantedBy = [ "initrd.target" ];
    after = [ "systemd-udev-settle.service" ];
    wants = [ "systemd-udev-settle.service" ];
    before = [ "sysroot.mount" "cryptsetup-pre.target" "aurora-initrd-root.service" ];
    serviceConfig.Type = "oneshot";
    serviceConfig.ExecStart = "${loadFirmware}/bin/aurora-load-vendor-firmware";
  };
  boot.initrd.systemd.storePaths = [ loadFirmware extractFirmware admission ] ++ map lib.getBin firmwareTools;
  systemd.services.aurora-vendor-firmware = {
    description = "Maintain Aurora per-device firmware handoff";
    wantedBy = [ "multi-user.target" ];
    after = [ "local-fs.target" ];
    before = [ "bluetooth.service" ];
    serviceConfig.Type = "oneshot";
    serviceConfig.RemainAfterExit = true;
    serviceConfig.ExecStart = "${loadFirmware}/bin/aurora-load-vendor-firmware runtime";
  };
}
