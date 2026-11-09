{ config, lib, pkgs, ... }:
let
  cfg = config.aurora.cameraDenoise;
  settings = lib.filterAttrs (_: value: value != null) cfg.settings;
in {
  options.aurora.cameraDenoise = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Start the denoise filter with each user's PipeWire service and enable
        PipeWire by default. It publishes filtered camera nodes while retaining
        the originals. False omits this integration, its settings and its
        default PipeWire enablement; PipeWire then follows other configuration.

        CPU filtering is built in. Additional backends must be installed in
        the selected package's `lib/aurora-camera-denoise` directory.
      '';
    };
    package = lib.mkPackageOption pkgs "aurora-camera-denoise" { };
    settings = lib.mkOption {
      type = lib.types.submodule {
        freeformType = lib.types.attrsOf (lib.types.oneOf [ lib.types.str lib.types.int lib.types.float ]);
        options = {
          mode = lib.mkOption {
            type = lib.types.nullOr (lib.types.enum [ "auto" "on" "off" ]);
            default = null;
            description = ''
              Trigger mode: `auto` follows gain/noise thresholds, `on` forces
              filtering, and `off` passes frames through. Temporal filtering
              is controlled separately. Null leaves the package default (`auto`).
            '';
          };
          temporal = lib.mkOption {
            type = lib.types.nullOr (lib.types.enum [ "on" "off" ]);
            default = null;
            description = ''
              `on` runs the temporal filter on every frame unless mode is `off`;
              `off` gates the selected backend with the trigger. Null leaves
              the package default (`on`).
            '';
          };
          backend = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = ''
              `auto` tries preferred installed plugins. With temporal filtering
              on, the CPU temporal filter remains when no plugin is usable;
              `cpu` selects that filter alone. With temporal filtering off,
              `auto` falls back to the CPU as the sole backend. Null keeps `auto`.
            '';
          };
          threads = lib.mkOption {
            type = lib.types.nullOr lib.types.ints.unsigned;
            default = null;
            description = "CPU worker count; 0 uses one worker. Null leaves the package default (0).";
          };
        };
      };
      default = { };
      example = { mode = "auto"; enter-gain = 1536; exit-gain = 1280; };
      description = ''
        Values for `[denoise]` in `/etc/aurora-camera-denoise/denoise.conf`;
        an empty set writes no file. Nix validates value types, not freeform
        key names or numeric ranges. Unknown keys fail daemon configuration;
        some numeric values are normalized instead of rejected.

        Gain/noise thresholds (`enter-gain`, `exit-gain`, `enter-noise`,
        `exit-noise`) override board data. Use nonnegative integer gains and
        frame counts. Zero `enter-gain` disables its trigger; nonpositive
        `enter-noise` disables the noise trigger. Exit thresholds are capped
        at their entry thresholds. `fps-threshold` defaults to 30; nonpositive
        values remove the frame-rate gate. `ramp-up-frames` and
        `ramp-down-frames` default to 0 and 30; zero makes transitions immediate.

        Other keys are `low-light-frame-rate` (`on` by default, permits longer
        exposures and lower frame rates), `prefer` (preferred plugin names,
        comma-separated; default `ane`) and `drivers` (camera driver names,
        comma-separated; default `apple-isp`). Strings, integers and floats are
        accepted as freeform values; use `"on"` or `"off"` for switch keys.
        These values override board data; each user's
        `~/.config/aurora-camera-denoise/denoise.conf` wins over this file.
        Running services pick up a change with
        `systemctl --user reload aurora-camera-denoise`.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    services.pipewire.enable = lib.mkDefault true;
    environment.systemPackages = [ cfg.package ];
    systemd.packages = [ cfg.package ];
    systemd.user.services.aurora-camera-denoise.wantedBy = [ "pipewire.service" ];
    environment.etc."aurora-camera-denoise/denoise.conf" = lib.mkIf (settings != { }) {
      text = lib.generators.toINI { } { denoise = settings; };
    };
  };
}
