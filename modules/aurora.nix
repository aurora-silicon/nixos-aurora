{ config, lib, pkgs, ... }:
{
  imports = [ ./firmware.nix ./platform.nix ./firstboot.nix ];
  options.aurora.desktop = lib.mkOption {
    type = lib.types.enum [ "kde" "gnome" "minimal" ];
    default = "kde";
    description = "Desktop selected by the Aurora native installer profile.";
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
    # The Apple kernel profile has no AHCI driver. Keep the Apple/USB/NVMe
    # initrd set explicit instead of inheriting generic PC storage modules.
    boot.initrd.availableKernelModules = lib.mkForce [
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
    boot.supportedFilesystems = [ "ext4" "btrfs" ];
    hardware.graphics.enable = true;
    services.desktopManager.plasma6.enable = config.aurora.desktop == "kde";
    services.displayManager.sddm.enable = config.aurora.desktop == "kde";
    services.desktopManager.gnome.enable = config.aurora.desktop == "gnome";
    services.displayManager.gdm.enable = config.aurora.desktop == "gnome";
    environment.systemPackages = [ pkgs.aurora-bless pkgs.git ];
    system.stateVersion = "26.05";
  };
}
