{ config, modulesPath, ... }:
{
  aurora.imageLayout = (builtins.fromJSON (builtins.readFile ../images/layouts.json)).${config.aurora.desktop};
  imports = [ (modulesPath + "/profiles/base.nix") ];
  fileSystems."/" = { device = "/dev/disk/by-label/AURORA_ROOT"; fsType = "btrfs"; options = [ "subvol=root" "compress=zstd:1" ]; };
  fileSystems."/home" = { device = "/dev/disk/by-label/AURORA_ROOT"; fsType = "btrfs"; options = [ "subvol=home" "compress=zstd:1" ]; };
  fileSystems."/boot" = { device = "/dev/disk/by-label/AURORA_BOOT"; fsType = "ext4"; };
  fileSystems."/boot/efi" = { device = "/dev/disk/by-label/AURORA_EFI"; fsType = "vfat"; };
  boot.loader.efi.efiSysMountPoint = "/boot/efi";
  # The shared first-boot adapter creates the Linux account; images carry no password.
  users.mutableUsers = true;
}
