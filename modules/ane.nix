{ config, lib, pkgs, ... }:
let cfg = config.aurora.ane;
in {
  options.aurora.ane = {
    enable = lib.mkEnableOption "ANE userspace tools and compiler";
    firmwarePackage = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = null;
      description = ''
        Owner-supplied, uncompressed firmware package with files under
        lib/firmware/apple/ane. Fetch locally with omarchy-ane-firmware-fetch;
        see docs/ane.md. No Apple firmware is included or fetched by a build.
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
