{ config, lib, pkgs, ... }:
{
  imports = [ ./firmware.nix ];
  options.aurora.desktop = lib.mkOption {
    type = lib.types.enum [ "kde" "gnome" "minimal" ];
    default = "kde";
    description = "Desktop selected by the Aurora native installer profile.";
  };
  config = {
    hardware.asahi.enable = true;
    nixpkgs.hostPlatform = "aarch64-linux";
    nix.settings.experimental-features = [ "nix-command" "flakes" ];
    networking.hostName = "aurora";
    networking.networkmanager.enable = true;
    boot.loader.grub.enable = true;
    boot.loader.grub.efiSupport = true;
    boot.loader.grub.efiInstallAsRemovable = true;
    boot.loader.grub.device = "nodev";
    boot.loader.efi.canTouchEfiVariables = false;
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
