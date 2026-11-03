{
  # QEMU (virt, virtio-gpu) LUKS2 test systems for nixos-aurora #120.
  # "test" takes boot-splash.nix and the Plymouth carry from the PR head,
  # "control" takes the Plymouth carry from the PR base (no boot-splash.nix).
  # Both use the stock nixpkgs kernel (the VM has no Apple display), so
  # appledrm cannot be found: allowMissingModules lets the initrd build.
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/e7439b6b14ad3cc35d05608ebca9bce01a25f5f8";
    head = { url = "path:/Volumes/AuroraS500/work/neo-plymouth-20261103/nixos-aurora"; flake = false; };
    base = { url = "path:/Volumes/AuroraS500/work/plymouth-parity-20261103/nixos-base"; flake = false; };
  };
  outputs = { self, nixpkgs, head, base }:
    let
      luksUUID = "5e1f0c7a-0a7e-4c55-9d6b-4a2c1f3b9e01";
      espUUID = "AE01-2026";
      mk = src: extra: nixpkgs.lib.nixosSystem {
        system = "aarch64-linux";
        modules = extra ++ [ ({ lib, pkgs, ... }: {
          nixpkgs.overlays = [ (final: prev: { plymouth = ((import "${src}/overlay.nix") final prev).plymouth; }) ];
          # As modules/aurora.nix sets them for desktop profiles.
          boot.plymouth.enable = true;
          boot.plymouth.package = pkgs.plymouth;
          boot.plymouth.theme = "spinner";
          boot.initrd.systemd.enable = true;
          boot.initrd.systemd.tpm2.enable = false;
          boot.initrd.allowMissingModules = true;
          boot.initrd.availableKernelModules = [ "virtio_pci" "virtio_blk" "virtio_gpu" "virtio_input" "dm-crypt" "ext4" "vfat" ];
          boot.initrd.luks.devices.cryptroot.device = "/dev/disk/by-uuid/${luksUUID}";
          boot.consoleLogLevel = 3;
          boot.initrd.verbose = false;
          boot.kernelParams = [ "quiet" "console=tty0" "console=ttyAMA0" "plymouth.ignore-serial-consoles"
            "rd.udev.log_level=3" "udev.log_level=3" "systemd.show_status=auto" ];
          fileSystems."/" = { device = "/dev/mapper/cryptroot"; fsType = "ext4"; };
          fileSystems."/boot" = { device = "/dev/disk/by-uuid/${espUUID}"; fsType = "vfat"; };
          boot.loader.grub.enable = true;
          boot.loader.grub.device = "nodev";
          boot.loader.grub.efiSupport = true;
          boot.loader.grub.efiInstallAsRemovable = true;
          boot.loader.efi.canTouchEfiVariables = false;
          networking.hostName = "aurora-vm";
          users.users.root.initialPassword = "aurora";
          documentation.enable = false;
          system.stateVersion = "26.05";
          # Report the unlock and the boot timings on the serial console.
          systemd.services.aurora-unlock-ok = {
            wantedBy = [ "multi-user.target" ];
            after = [ "local-fs.target" "systemd-journald.service" ];
            serviceConfig.Type = "oneshot";
            path = [ pkgs.util-linux pkgs.systemd pkgs.gnugrep pkgs.coreutils ];
            script = ''
              {
                echo "AURORA-UNLOCK-OK $(findmnt -no SOURCE /)"
                grep -o 'After=.*' /etc/systemd/system/plymouth-start.service 2>/dev/null || true
                journalctl -b -o short-monotonic --no-pager | grep -E 'Show Plymouth Boot Screen|Forward Password Requests to Plymouth|Coldplug All udev|Apple display|Cryptography Setup|cryptroot|Switching root|Reached target.*Initrd' | sed 's/^/J /' || true
                echo AURORA-REPORT-END
              } > /dev/ttyAMA0
            '';
          };
        }) ];
      };
    in {
      nixosConfigurations.test = mk head [ "${head}/modules/boot-splash.nix" ];
      nixosConfigurations.control = mk base [ ];
    };
}
