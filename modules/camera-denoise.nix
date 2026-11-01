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
        Run aurora-camera-denoise, a PipeWire filter that denoises the built-in
        camera the way macOS does, as a user service for every user. It adds a
        filtered node next to each built-in camera. A temporal filter runs on
        every frame, and a low-light stage (a backend plugin) joins in above
        the per-board gain levels in its boards.conf.

        Backends load from the package's own `lib/aurora-camera-denoise`. The
        CPU backend is built in; a Neural Engine backend has to be built into
        the same package until its path becomes configurable.
      '';
    };
    package = lib.mkPackageOption pkgs "aurora-camera-denoise" { };
    settings = lib.mkOption {
      type = lib.types.submodule {
        freeformType = lib.types.attrsOf (lib.types.oneOf [ lib.types.str lib.types.int ]);
        options = {
          mode = lib.mkOption {
            type = lib.types.nullOr (lib.types.enum [ "auto" "on" "off" ]);
            default = null;
            description = "`auto` runs the temporal filter always and the low-light stage by sensor gain and noise, `on` runs both always, `off` passes frames through.";
          };
          temporal = lib.mkOption {
            type = lib.types.nullOr (lib.types.enum [ "on" "off" ]);
            default = null;
            description = "`on` (the default) runs the temporal filter on every frame, like macOS; `off` only filters above the low-light levels.";
          };
          backend = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = "`auto` uses an installed Neural Engine backend when it works, else the CPU; `cpu` always uses the CPU.";
          };
          threads = lib.mkOption {
            type = lib.types.nullOr lib.types.ints.unsigned;
            default = null;
            description = "CPU worker threads; 0 means one, which costs the least CPU.";
          };
        };
      };
      default = { };
      example = { mode = "auto"; enter-gain = 1536; exit-gain = 1280; };
      description = ''
        The `[denoise]` section of /etc/aurora-camera-denoise/denoise.conf.
        Board levels (`enter-gain`, `exit-gain`, `enter-noise`, `exit-noise`,
        `fps-threshold`, `ramp-up-frames`, `ramp-down-frames`) override the
        board data. Each user's ~/.config/aurora-camera-denoise/denoise.conf
        wins over this file. Running services pick up a change with
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
