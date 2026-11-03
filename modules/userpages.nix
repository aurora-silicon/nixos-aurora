{ config, lib, pkgs, ... }:
{
  options.aurora.userpages.enable = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = ''
      Per-process 4K userspace pages: user4k=on on the kernel command line and
      the userpages launcher (userpages 4k COMMAND). Turn them off with this
      option, or with boot.kernelParams = [ "user4k=off" ].
    '';
  };
  config = lib.mkIf config.aurora.userpages.enable {
    # First on the command line, so a user4k= the owner adds later wins.
    boot.kernelParams = lib.mkBefore [ "user4k=on" ];
    environment.systemPackages = [ pkgs.aurora-userpages ];
  };
}
