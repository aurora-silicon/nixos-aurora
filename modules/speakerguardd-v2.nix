{ config, lib, pkgs, ... }:
# speakerguardd 1.0 (the v2 branch), the in-graph speaker protection.
# Opt-in (default false): speakersafetyd stays the speaker protection. With
# enable = true it is installed beside the 0.1 speakerguardd and
# speakersafetyd, and its gate (speakerguardd-gate, upstream's) starts exactly
# one stack per boot. On a dual-interface kernel (linux 98cb6a86+) that is
# speakersafetyd until aurora-speaker-upgrade made v2 this Mac's choice and
# every proof passed; on a legacy-only kernel it is always speakersafetyd.
# Fedora's and ALARM's speakerguardd-v2 packages are its counterparts.
let
  cfg = config.aurora.speakerguardd.v2;
  lx = "${cfg.package}/libexec/speakerguardd-v2";
  # What provisioning, the gate, the self-check and the session helper run:
  # the ALSA tools, pw-link and pw-dump, loginctl and systemctl, and the
  # tuning reader.
  tools = [ pkgs.alsa-utils pkgs.pipewire pkgs.systemd cfg.package ];
  # "+": the gate runs privileged even in a DynamicUser unit (speakersafetyd), speakerguardd#131.
  legacyGate = { serviceConfig.ExecCondition = [ "+${lx}/speakerguardd-gate legacy" ]; };
in {
  options.aurora.speakerguardd.v2 = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Install speakerguardd 1.0 beside the 0.1 speakerguardd and
        speakersafetyd, with its gate on both stacks. Nothing changes for the
        speakers by itself: the gate keeps speakersafetyd in charge until
        aurora-speaker-upgrade (aurora.speakerguardd.upgrade.enable) has
        verified this Mac's own tuning and switched the dual-interface
        kernel to v2's lease. Off by default.
      '';
    };
    package = lib.mkPackageOption pkgs "speakerguardd-v2" { };
  };

  imports = [
    (lib.mkRemovedOptionModule [ "aurora" "speakerguardd" "v2" "replaceLegacy" ]
      "aurora.speakerguardd.v2.enable installs v2 beside the legacy daemons; aurora-speaker-upgrade makes the switch.")
  ];

  config = lib.mkMerge [ (lib.mkIf cfg.enable {
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
    # The older daemons start only where v2 does not run and the kernel has
    # no v2 interface.
    systemd.services.speakersafetyd = legacyGate;
    systemd.services.speakerguardd = legacyGate;
  })
  (lib.mkIf (!cfg.enable) {
      # The preview linked its generated PipeWire and WirePlumber configuration
      # into each user's ~/.config, pointing into /run/speakerguardd-graph. Nothing
      # creates that directory without v2, so the links dangle and PipeWire logs an
      # error at every login. Remove only links into that directory, at every boot
      # and switch; /var/lib/speakerguardd stays for aurora-speaker-upgrade.
      system.activationScripts.aurora-audio-v2-cleanup.text = let
        cleanup = pkgs.writeShellApplication {
          name = "aurora-audio-v2-cleanup";
          runtimeInputs = [ pkgs.getent pkgs.coreutils ];
          # writeShellApplication writes its own shebang (shellcheck SC1128).
          text = lib.removePrefix "#!/bin/sh\n" (builtins.readFile ./aurora-audio-v2-cleanup);
        };
      in "${cleanup}/bin/aurora-audio-v2-cleanup || true";
  }) ];
}
