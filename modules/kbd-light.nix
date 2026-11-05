{ config, lib, pkgs, ... }:
let
  cfg = config.aurora.kbdLight;
  names = {
    fullLux = "AURORA_KBD_LIGHT_FULL_LUX";
    onLux = "AURORA_KBD_LIGHT_ON_LUX";
    offLux = "AURORA_KBD_LIGHT_OFF_LUX";
    minPercent = "AURORA_KBD_LIGHT_MIN_PERCENT";
    maxPercent = "AURORA_KBD_LIGHT_MAX_PERCENT";
  };
  environment = lib.mapAttrs' (name: value: lib.nameValuePair names.${name} (toString value))
    (lib.filterAttrs (_: value: value != null) cfg.settings);
  number = description: lib.mkOption {
    type = lib.types.nullOr (lib.types.either lib.types.ints.unsigned lib.types.float);
    default = null;
    inherit description;
  };
in {
  options.aurora.kbdLight = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Run aurora-kbd-light, which sets the keyboard backlight from the
        ambient light sensor the way macOS does: brightest in the dark, off in
        daylight, with the lid closed and while the displays sleep. A level set from the desktop is
        respected. Without a keyboard backlight the service does not start.
      '';
    };
    package = lib.mkPackageOption pkgs "aurora-kbd-light" { };
    settings = lib.mkOption {
      type = lib.types.submodule {
        options = {
          fullLux = number "At or below this many lux, the brightest automatic level.";
          onLux = number "Below this many lux the backlight comes on.";
          offLux = number "Above this many lux it goes off again.";
          minPercent = number "Level, in percent, just after it comes on.";
          maxPercent = number "Level, in percent, in the dark.";
        };
      };
      default = { };
      example = { maxPercent = 70; };
      description = "Overrides of the daemon's defaults, set in its environment.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];
    systemd.packages = [ cfg.package ];
    systemd.services.aurora-kbd-light = {
      wantedBy = [ "multi-user.target" ];
      inherit environment;
    };
  };
}
