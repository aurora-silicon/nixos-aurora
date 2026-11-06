{ lib, pkgs, ... }:
let
  admission = pkgs.runCommand "aurora-peripheral-admission" { } ''
    install -Dm755 ${../firmware/aurora-peripheral-firmware.sh} $out/bin/aurora-peripheral-admission
    patchShebangs $out/bin/aurora-peripheral-admission
  '';
  firmwareTools = [ pkgs.coreutils pkgs.util-linux pkgs.cpio pkgs.kmod pkgs.gnugrep pkgs.bash pkgs.systemd ];
  extractFirmware = pkgs.writeShellApplication {
    name = "aurora-extract-vendor-firmware";
    runtimeInputs = firmwareTools;
    text = ''
      property=/sys/firmware/devicetree/base/chosen/asahi,efi-system-partition
      if [ ! -r "$property" ]; then exit 0; fi
      uuid=$(tr -d '\000' < "$property")
      [[ "$uuid" =~ ^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$ ]] || {
        echo 'Invalid Apple EFI partition identity' >&2; exit 1;
      }
      uuid=''${uuid,,}
      device=/dev/disk/by-partuuid/$uuid
      destination=/run/aurora-firmware
      mkdir -p "$destination"
      if [ ! -s "$destination/vendorfw/.vendorfw.manifest" ]; then
        udevadm wait --timeout=60 "$device"
        # The installed system mounts the ESP read-write, and the kernel
        # refuses a second, read-only mount of it, so a retry there reads it
        # in place.
        esp=$(findmnt --noheadings --first-only --output TARGET --source "$device" || true)
        if [ -z "$esp" ]; then
          esp=/run/aurora-esp
          mkdir -p "$esp"
          mount -t vfat -o ro "$device" "$esp"
          trap 'umount /run/aurora-esp' EXIT
        fi
        if [ ! -s "$esp/vendorfw/firmware.cpio" ]; then
          # Nothing to hand off; peripherals are still admitted.
          echo '<4>Aurora: the ESP has no vendor firmware; admitting peripherals without it' >&2
          exit 0
        fi
        # Unconditional, so a retry replaces what a failed attempt left behind.
        (cd "$destination"; cpio --quiet --extract --unconditional --no-absolute-filenames < "$esp/vendorfw/firmware.cpio")
      fi
    '';
  };
  loadFirmware = pkgs.writeShellApplication {
    name = "aurora-load-vendor-firmware";
    runtimeInputs = firmwareTools;
    text = ''
      destination=/run/aurora-firmware
      # Extraction runs as its own process so that its errors stop it, while
      # the keyboard and the other peripherals are still admitted below.
      status=0
      ${extractFirmware}/bin/aurora-extract-vendor-firmware || status=$?
      if [[ "$status" != 0 && "''${1:-initrd}" != runtime ]]; then
        # The installed system's aurora-vendor-firmware.service retries the
        # handoff and reports its result.
        echo '<4>Aurora: vendor firmware handoff failed; the installed system will retry it' >&2
        status=0
      fi
      export AURORA_FIRMWARE_ROOT="$destination/vendorfw"
      export AURORA_ADMIT_BLUETOOTH=0
      if [[ "''${1:-initrd}" == runtime ]]; then
        # Activation replaces the initrd's firmware_class.path with the Nix
        # store firmware tree. Restore the per-device path while retaining the
        # store tree through the kernel's standard /lib/firmware fallback.
        if [[ ! -e /lib/firmware && ! -L /lib/firmware ]]; then
          ln -s /run/current-system/firmware /lib/firmware
        fi
        [[ -d /lib/firmware ]] || { echo 'System firmware fallback is unavailable' >&2; exit 1; }
        printf '%s' "$destination/vendorfw" > /sys/module/firmware_class/parameters/path
        export AURORA_ADMIT_BLUETOOTH=1
      fi
      ${admission}/bin/aurora-peripheral-admission
      exit "$status"
    '';
  };
in {
  # The distributable image cannot embed another Mac's calibration in /nix/store.
  # Replace build-time extraction with an initrd/runtime ESP handoff.
  hardware.asahi.extractPeripheralFirmware = lib.mkDefault false;
  boot.kernelParams = [ "firmware_class.path=/run/aurora-firmware/vendorfw" ];
  # The keyboard driver probes from the admission script, after the ESP
  # firmware reaches the initrd, so it is in the initrd but not autoloaded.
  boot.blacklistedKernelModules = [ "aop" "mt7932-fullmac" "mt7932_bt_pcie" "dockchannel-hid" ];
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
