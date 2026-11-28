{ config, lib, pkgs, ... }:
{
  options.aurora.userpages.enable = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = ''
      Install the `userpages` launcher (`userpages 4k COMMAND`). The kernel
      offers 4K userspace pages without a kernel parameter;
      `boot.kernelParams = [ "user4k=off" ];` turns them off. Kernel-command-line
      changes need a reboot.
    '';
  };
  config = lib.mkIf config.aurora.userpages.enable {
    environment.systemPackages = [ pkgs.aurora-userpages ];
  };
}
