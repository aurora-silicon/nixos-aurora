{ config, lib, pkgs, ... }:
# speakerguardd 1.0 (the v2 branch), the in-graph speaker protection. It is
# installed on every Mac beside the 0.1 speakerguardd and speakersafetyd, and
# its fleet gate (speakerguardd-gate, upstream's, with upstream's data)
# starts exactly one stack per boot: v2 on a board gated for it whose kernel
# has the v2 interface, the older daemons everywhere else. Fedora's and
# ALARM's speakerguardd-v2 packages are its counterparts.
let
  cfg = config.aurora.speakerguardd.v2;
  lx = "${cfg.package}/libexec/speakerguardd-v2";
  # What provisioning, the gate, the self-check and the session helper run:
  # the ALSA tools, pw-link and pw-dump, loginctl and systemctl, and the
  # tuning reader.
  tools = [ pkgs.alsa-utils pkgs.pipewire pkgs.systemd cfg.package ];
  legacyGate = { serviceConfig.ExecCondition = [ "${lx}/speakerguardd-gate legacy" ]; };
in {
  options.aurora.speakerguardd.v2 = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Install speakerguardd 1.0 beside the 0.1 speakerguardd and
        speakersafetyd, with the fleet gate on both stacks. At every boot the
        gate starts exactly one of them: speakerguardd 1.0 on a board whose
        protection unit is at parity and that qualified, when the kernel has
        the v2 interface ("Speaker Protection"); the older daemons
        everywhere else. On a fleet kernel without the v2 interface nothing
        changes. On a gated board, provisioning compiles the Mac's own tuning,
        resolves the seat user by name and writes the configuration, with no
        manual step. Set it to false to remove speakerguardd 1.0 and its gate:
        the older daemons then run as before.
      '';
    };
    package = lib.mkPackageOption pkgs "speakerguardd-v2" { };
  };

  imports = [
    (lib.mkRemovedOptionModule [ "aurora" "speakerguardd" "v2" "replaceLegacy" ]
      "speakerguardd 1.0 is installed on every Mac and its fleet gate picks the stack per boot; there is no opt-in any more.")
  ];

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];
    environment.pathsToLink = [ "/lib/lv2" ];
    systemd.packages = [ cfg.package ];
    # Every v2 system unit carries the gate itself (ExecCondition= in the
    # upstream unit). Provisioning and the self-check are pulled in by the
    # supervisor (Requires= and After= in its unit).
    systemd.services.speakerguardd-v2 = { wantedBy = [ "multi-user.target" ]; path = tools; };
    systemd.services.speakerguardd-v2-provision.path = tools;
    systemd.services.speakerguardd-v2-selfcheck.path = tools;
    systemd.services.speakerguardd-v2-seat.path = tools;
    # Before every sleep: the amps unlinked and the supervisor stopped while
    # awake; after the resume it starts again and grants.
    systemd.services.speakerguardd-v2-sleep = { wantedBy = [ "sleep.target" ]; path = tools; };
    systemd.paths.speakerguardd-v2-seat.wantedBy = [ "multi-user.target" ];
    systemd.user.services.speakerguardd-v2-graph = { wantedBy = [ "pipewire.service" ]; path = tools; };
    systemd.user.services.speakerguardd-v2-session = { wantedBy = [ "pipewire.service" ]; path = tools; };
    # The older daemons start only where v2 does not run and the kernel has
    # no v2 interface.
    systemd.services.speakersafetyd = legacyGate;
    systemd.services.speakerguardd = legacyGate;
  };
}
