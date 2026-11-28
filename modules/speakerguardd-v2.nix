{ config, lib, pkgs, ... }:
# speakerguardd 1.0, the in-graph speaker protection: the only speaker stack
# and the only program that takes the kernel's speaker interlock. The option
# defaults to false; the Aurora platform turns it on (modules/platform.nix)
# with aurora-speaker-upgrade. Its gate (speakerguardd-gate, upstream's)
# starts it on a qualified board whose kernel has the v2 interface; any other
# board runs no speaker daemon and the kernel holds its speakers at its floor.
# Fedora's and ALARM's speakerguardd-v2 packages are its counterparts.
let
  cfg = config.aurora.speakerguardd.v2;
  # What provisioning, the gate, the self-check and the session helper run:
  # the ALSA tools, pw-link and pw-dump, loginctl and systemctl, and the
  # tuning reader, setpriv and runuser for reaching the seat user's session.
  tools = [ pkgs.alsa-utils pkgs.pipewire pkgs.systemd pkgs.util-linux cfg.package ];
in {
  options.aurora.speakerguardd.v2 = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Install speakerguardd 1.0, the only speaker protection. Its gate
        starts it on a qualified board once aurora-speaker-upgrade
        (aurora.speakerguardd.upgrade.enable) has verified this Mac's own
        tuning and switched the dual-interface kernel to v2's lease; without
        it the kernel holds the speakers at its floor. The Aurora platform
        turns it on.
      '';
    };
    package = lib.mkPackageOption pkgs "speakerguardd-v2" { };
  };

  imports = [
    (lib.mkRemovedOptionModule [ "aurora" "speakerguardd" "v2" "replaceLegacy" ]
      "speakerguardd v2 is the only speaker stack: speakersafetyd and speakerguardd 0.1 are no longer shipped.")
  ];

  config = lib.mkIf cfg.enable {
    # The provisioning marker (speakerguardd#106) hides the speaker card's raw
    # ports; without aurora-audio's keep-profile rule (asahi-audio#24) a Mac
    # with a headphone jack drops the built-in card to "off" while nothing is
    # plugged in. Fedora and ALARM carry the same hard requirement.
    assertions = [{
      # The kernel serves both speaker interfaces (linux#1279); a v2 that does
      # not know it refuses and leaves the speakers silent.
      assertion = cfg.package.passthru.dualInterface or false;
      message = "aurora.speakerguardd.v2 needs speakerguardd-v2 RC8.2 or later (dual-interface kernel, speakerguardd#117/#131/#134); this package predates it.";
    } {
      assertion = pkgs.asahi-audio.keepsBuiltinProfile or false;
      message = "aurora.speakerguardd.v2 needs Aurora's asahi-audio (aurora-audio >= 4.1-11, asahi-audio#24) with asahi-keep-profile.lua.";
    }];
    environment.systemPackages = [ cfg.package ];
    environment.pathsToLink = [ "/lib/lv2" ];
    services.pipewire.extraLv2Packages = [ cfg.package ];
    systemd.packages = [ cfg.package ];
    # Every v2 system unit carries the gate itself (ExecCondition= in the
    # upstream unit). Provisioning and the self-check (with its switch test
    # after login) are pulled in by the supervisor (Requires= and After= in
    # its unit).
    systemd.services.speakerguardd-v2 = { wantedBy = [ "multi-user.target" ]; path = tools; };
    systemd.services.speakerguardd-v2-provision.path = tools;
    systemd.services.speakerguardd-v2-selfcheck.path = tools;
    systemd.services.speakerguardd-v2-switchtest.path = tools;
    systemd.services.speakerguardd-v2-seat.path = tools;
    # Before every sleep: the amps unlinked and the supervisor stopped while
    # awake; after the resume it starts again and grants.
    systemd.services.speakerguardd-v2-sleep = { wantedBy = [ "sleep.target" ]; path = tools; };
    systemd.paths.speakerguardd-v2-seat.wantedBy = [ "multi-user.target" ];
    systemd.user.services.speakerguardd-v2-graph = { wantedBy = [ "pipewire.service" ]; path = tools; };
    systemd.user.services.speakerguardd-v2-session = { wantedBy = [ "pipewire.service" ]; path = tools; };
  };
}
