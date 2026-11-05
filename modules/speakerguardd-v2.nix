{ config, lib, pkgs, ... }:
# speakerguardd 1.0 (the v2 branch), the in-graph speaker protection. It is a
# new program, installed beside the 0.1 speakerguardd and speakersafetyd;
# Fedora's speakerguardd-v2 and speakerguardd-v2-replace-legacy packages and
# ALARM's PKGBUILD of the same names are its counterparts.
let
  cfg = config.aurora.speakerguardd.v2;
  gate = "${cfg.package}/libexec/speakerguardd-v2/speakerguardd-v2-gate";
  # What the self-check and the session helper run: the ALSA tools for the
  # silent switch test, pw-link and pw-dump, and the tuning reader.
  tools = [ pkgs.alsa-utils pkgs.pipewire cfg.package ];
in {
  options.aurora.speakerguardd.v2 = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = cfg.replaceLegacy;
      defaultText = lib.literalExpression "config.aurora.speakerguardd.v2.replaceLegacy";
      description = ''
        Install speakerguardd 1.0 beside the 0.1 speakerguardd and
        speakersafetyd: the supervisor's unit, speakerguardd-v2.service, the
        first-boot wiring self-check and the session helper's user unit (none
        started), the sgv2 LV2 plugin on the LV2 path and
        aurora-speaker-tuning. This changes nothing on its own: the unit
        stays off, and no graph loads the plugin.
      '';
    };
    replaceLegacy = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Opt in: make speakerguardd 1.0 this machine's speaker protection. It
        masks the 0.1 speakerguardd and speakersafetyd, so neither they nor
        their udev rules can start, and starts speakerguardd-v2.service at
        boot, with its self-check and session helper, on a qualified board
        only (speakerguardd-v2-gate; J616s and J316s for now). Set it only on a machine
        that passed the 1.0 qualification
        (parity with macOS, fault injection, a clean boot log, and loudness
        and clarity against macOS); until then the machine keeps the
        protection it runs today.
      '';
    };
    package = lib.mkPackageOption pkgs "speakerguardd-v2" { };
  };

  config = lib.mkMerge [
    (lib.mkIf cfg.enable {
      environment.systemPackages = [ cfg.package ];
      environment.pathsToLink = [ "/lib/lv2" ];
      systemd.packages = [ cfg.package ];
    })
    (lib.mkIf cfg.replaceLegacy {
      assertions = [{
        assertion = cfg.enable;
        message = "aurora.speakerguardd.v2.replaceLegacy needs aurora.speakerguardd.v2.enable.";
      }];
      # The older daemons must not hold the speaker interlock beside it.
      systemd.services.speakerguardd.enable = false;
      systemd.services.speakersafetyd.enable = false;
      # The supervisor pulls in its hard prerequisite, the first-boot wiring
      # self-check (Requires= and After= in the unit). Every unit carries the
      # board gate, the same speakerguardd-v2-gate as on Fedora and ALARM:
      # on a board that has not qualified on 1.0 none starts, and the journal
      # says why.
      systemd.services.speakerguardd-v2 = {
        wantedBy = [ "multi-user.target" ];
        serviceConfig.ExecCondition = gate;
      };
      systemd.services.speakerguardd-v2-selfcheck = {
        requiredBy = [ "speakerguardd-v2.service" ];
        path = tools;
        serviceConfig.ExecCondition = gate;
      };
      systemd.user.services.speakerguardd-v2-session = {
        wantedBy = [ "pipewire.service" ];
        path = tools;
        serviceConfig.ExecCondition = gate;
      };
    })
  ];
}
