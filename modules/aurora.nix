{ config, lib, pkgs, ... }:
{
  imports = [ ./firmware.nix ./platform.nix ./audio.nix ./system-fixes.nix
    ./flatpak.nix ./fex-mesa.nix ./parity.nix ./branding.nix
    ./firstboot.nix ./plasma-setup.nix ./gnome-initial-setup.nix ./sep.nix ];
  options.aurora.desktop = lib.mkOption {
    type = lib.types.enum [ "kde" "gnome" "minimal" ];
    default = "kde";
    description = "Desktop selected by the Aurora native installer profile.";
  };
  options.aurora.openssh.startAtBoot = lib.mkOption {
    type = lib.types.bool;
    default = false;
    description = ''
      Start the OpenSSH server (and its host key generation) at boot. Off by
      default: the server is installed but starts only on request.
    '';
  };
  config = {
    hardware.asahi.enable = true;
    nixpkgs.hostPlatform = "aarch64-linux";
    nix.settings.extra-substituters = [ "https://aurorasilicon.org/nixos-aurora/cache" ];
    nix.settings.extra-trusted-public-keys = [ (lib.removeSuffix "\n" (builtins.readFile ../keys/cache.pub)) ];
    nix.settings.experimental-features = [ "nix-command" "flakes" ];
    networking.hostName = lib.mkDefault "aurora";
    networking.networkmanager.enable = true;
    boot.loader.grub.enable = true;
    boot.loader.grub.efiSupport = true;
    boot.loader.grub.efiInstallAsRemovable = true;
    boot.loader.grub.device = "nodev";
    boot.loader.efi.canTouchEfiVariables = false;
    # Keep the Apple/USB/NVMe initrd set explicit. Native module additions
    # (including audio, sensors and systemd) still merge into this list.
    boot.initrd.includeDefaultModules = false;
    boot.initrd.availableKernelModules = [
      "apple-mailbox" "apple_nvmem_spmi" "nvme_apple" "pinctrl-apple-gpio"
      "macsmc" "macsmc-power" "macsmc-input" "macsmc-hwmon" "macsmc-reboot"
      "i2c-pasemi-platform" "tps6598x" "sn201202x" "apple-dart" "dwc3"
      "dwc3-of-simple" "xhci-pci" "pcie-apple" "gpio_macsmc" "phy-apple-atc"
      "nvmem_apple_efuses" "spi-apple" "spi-hid-apple" "spi-hid-apple-of"
      "rtc-macsmc" "spmi-apple-controller" "apple-dockchannel" "dockchannel-hid"
      "apple-rtkit-helper" "usb-storage" "xhci-plat-hcd" "usbhid" "hid_generic"
      "nvme" "virtio_blk" "virtio_pci" "uas" "sd_mod"
      "vfat" "dm-crypt" "btrfs" "ext4" "aop" "mt7932-fullmac" "mt7932_bt_pcie"
    ];
    # Apple silicon Macs have no TPM, and the shared distribution kernel has no
    # TPM drivers (its TPM 2.0 CRB interface would need ACPI). Do not ask the
    # systemd initrd for tpm-tis and tpm-crb.
    boot.initrd.systemd.tpm2.enable = lib.mkDefault false;
    boot.supportedFilesystems = [ "ext4" "btrfs" ];
    # Quiet by default: failures still reach the console, and systemd shows
    # status only when a unit fails or stalls.
    boot.consoleLogLevel = lib.mkDefault 3;
    boot.initrd.verbose = lib.mkDefault false;
    boot.kernelParams = [ "quiet" "rd.udev.log_level=3" "udev.log_level=3" "systemd.show_status=auto" ];
    # Desktop images boot to a splash; first boot asks for the disk password
    # on it, as every later boot does. The spinner theme needs no ACPI BGRT
    # firmware logo. Plymouth runs in the systemd initrd.
    boot.plymouth.enable = lib.mkDefault (config.aurora.desktop != "minimal");
    boot.plymouth.theme = lib.mkDefault "spinner";
    hardware.graphics.enable = true;
    hardware.graphics.extraPackages = [ pkgs.aurora-rusticl pkgs.aurora-lavapipe ];
    services.desktopManager.plasma6.enable = config.aurora.desktop == "kde";
    services.displayManager.sddm.enable = config.aurora.desktop == "kde";
    services.desktopManager.gnome.enable = config.aurora.desktop == "gnome";
    services.displayManager.gdm.enable = config.aurora.desktop == "gnome";
    # Every Aurora desktop image comes with a web browser, as Fedora and ALARM do.
    programs.firefox.enable = config.aurora.desktop != "minimal";
    # Every image has the OpenSSH server, but nothing starts it: no unit at
    # boot wants sshd or its host key generation, and the firewall keeps
    # port 22 closed. `sudo systemctl start sshd` starts it without a rebuild
    # and makes the host keys on first use. Remote clients also need the
    # port: `sudo nixos-firewall-tool open tcp 22` until the next firewall
    # reload, or services.openssh.openFirewall. aurora.openssh.startAtBoot
    # starts it at every boot.
    services.openssh.enable = lib.mkDefault true;
    services.openssh.openFirewall = lib.mkDefault false;
    systemd.services.sshd = lib.mkIf (config.services.openssh.enable && !config.services.openssh.startWhenNeeded
      && !config.aurora.openssh.startAtBoot) { wantedBy = lib.mkForce [ ]; };
    systemd.services.sshd-keygen = lib.mkIf (config.services.openssh.enable && config.services.openssh.generateHostKeys
      && !config.aurora.openssh.startAtBoot) { wantedBy = lib.mkForce [ ]; };
    # GDM keeps the splash until its greeter starts and replaces
    # plymouth-quit.service; give SDDM the same role, so the splash is still up
    # when first boot asks for the disk password. If SDDM fails,
    # plymouth-quit.service still removes the splash.
    systemd.services.display-manager = lib.mkIf (config.services.displayManager.sddm.enable && config.boot.plymouth.enable) {
      conflicts = [ "plymouth-quit.service" ];
      after = [ "plymouth-start.service" ];
      onFailure = [ "plymouth-quit.service" ];
      serviceConfig.ExecStartPre = [
        "-${pkgs.coreutils}/bin/timeout --kill-after=2 20 ${lib.getExe' config.boot.plymouth.package "plymouth"} quit"
      ];
    };
    # As with GDM: if multi-user.target wanted plymouth-quit.service, a
    # nixos-rebuild switch would stop the display manager to start it.
    systemd.services.plymouth-quit = lib.mkIf (config.services.displayManager.sddm.enable && config.boot.plymouth.enable) {
      wantedBy = lib.mkForce [ ];
    };
    environment.systemPackages = [ pkgs.aurora-bless pkgs.git pkgs.cryptsetup pkgs.btrfs-progs ];
    system.stateVersion = "26.05";
  };
}
