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
    description = description + " Null leaves the selected package's default.";
  };
in {
  options.aurora.kbdLight = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Start the keyboard-backlight service at boot. It follows ambient light,
        turns off with the lid closed or displays asleep, and respects manual
        desktop adjustments. Without a keyboard backlight the service is skipped.
        False removes the service integration and its environment settings.
      '';
    };
    package = lib.mkPackageOption pkgs "aurora-kbd-light" { };
    settings = lib.mkOption {
      type = lib.types.submodule {
        options = {
          fullLux = number "Lux at or below which the maximum level is used; positive and below onLux. The default package uses 2.";
          onLux = number "Lux below which the backlight turns on; above fullLux and at most offLux. The default package uses 60.";
          offLux = number "Lux above which the backlight turns off; at least onLux. The default package uses 120.";
          minPercent = number "Initial automatic level in percent; the daemon limits it to maxPercent. The default package uses 10.";
          maxPercent = number "Automatic level in darkness, capped at 100 percent by the daemon. The default package uses 50.";
        };
      };
      default = { };
      example = { maxPercent = 70; };
      description = ''
        Overrides passed through the service environment; null fields leave
        package defaults. Use nonnegative numbers and
        `0 < fullLux < onLux <= offLux`; the daemon enforces this ordering,
        not the Nix option types. Percentage fractions are truncated by
        the daemon. Its optional `/etc/default/aurora-kbd-light` environment
        file remains supported and takes precedence over these values.
      '';
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
