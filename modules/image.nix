{ config, modulesPath, ... }:
{
  imports = [ (modulesPath + "/profiles/base.nix") ];
  fileSystems."/" = { device = "/dev/disk/by-label/AURORA_ROOT"; fsType = "ext4"; };
  fileSystems."/boot" = { device = "/dev/disk/by-label/AURORA_BOOT"; fsType = "ext4"; };
  fileSystems."/boot/efi" = { device = "/dev/disk/by-label/AURORA_EFI"; fsType = "vfat"; };
  boot.loader.efi.efiSysMountPoint = "/boot/efi";
  # Account creation is supplied by the installer; no baked-in default password.
  users.mutableUsers = true;
}
