{ config, lib, pkgs, ... }:
let cfg = config.aurora.ane;
in {
  options.aurora.ane = {
    enable = lib.mkEnableOption "Apple Neural Engine (ANE) userspace tools and compiler" // {
      description = ''
        Install the Apple Neural Engine (ANE) tools and compiler, create the `accel` group and add
        device access rules. Disabling this omits that userspace integration;
        it does not change the kernel driver or fetch firmware.
      '';
    };
    firmwarePackage = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = null;
      description = ''
        Optional owner-supplied firmware package with uncompressed files under
        `lib/firmware/apple/ane`. Used only when `aurora.ane.enable` is true;
        null adds no firmware. Fetch locally with `omarchy-ane-firmware-fetch`;
        no Apple firmware is included or fetched by a build.
      '';
    };
  };
  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ pkgs.omarchy-ane-tools pkgs.mil-hwx-compiler ];
    users.groups.accel = { };
    services.udev.packages = [ pkgs.omarchy-ane-tools ];
    hardware.firmware = lib.optional (cfg.firmwarePackage != null)
      (cfg.firmwarePackage // { compressFirmware = false; });
    # The firmware validator and fetcher pin the raw image, not a .zst file.
    # Slot for the independently released shared inference runtime (t-3650).
    # Add its package here only once its API and release pin are available.
  };
}
