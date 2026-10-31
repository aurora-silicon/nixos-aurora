{ config, lib, pkgs, ... }:
{
  options.aurora.storage.appleNvmeScheduler = (lib.mkEnableOption
    "the none scheduler default for Apple ANS namespace disks") // { default = true; };

  config = lib.mkIf config.aurora.storage.appleNvmeScheduler {
    services.udev.packages = [ (pkgs.writeTextDir
      "lib/udev/rules.d/60-aurora-apple-nvme.rules"
      (builtins.readFile ../storage/60-aurora-apple-nvme.rules)) ];
  };
}
