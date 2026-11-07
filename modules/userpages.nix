{ config, lib, pkgs, ... }:
{
  options.aurora.userpages.enable = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = ''
      Add `user4k=on` first on the kernel command line and install the
      `userpages` launcher (`userpages 4k COMMAND`). False omits both.
      `boot.kernelParams = [ "user4k=off" ];` overrides the boot selection
      while retaining the launcher. Kernel-command-line changes need a reboot.
    '';
  };
  config = lib.mkIf config.aurora.userpages.enable {
    # First on the command line, so a user4k= the owner adds later wins.
    boot.kernelParams = lib.mkBefore [ "user4k=on" ];
    environment.systemPackages = [ pkgs.aurora-userpages ];
  };
}
