{ config, lib, pkgs, ... }:
{
  # aurora-speaker-upgrade moves a Mac's speakers to speakerguardd v2 with its
  # own tuning from the pinned macOS restore image. The Aurora platform turns
  # it on by default (`aurora.speakers.stack = "sgv2"`).
  options.aurora.speakerguardd.upgrade.enable = lib.mkOption {
    type = lib.types.bool;
    default = false;
    description = "Install aurora-speaker-upgrade and run it at boot: it moves the speakers to speakerguardd v2 when this Mac's own tuning passes the silent self-check (needs aurora.speakerguardd.v2.enable). The Aurora platform turns it on when `aurora.speakers.stack` is `\"sgv2\"`.";
  };
  config = lib.mkIf config.aurora.speakerguardd.upgrade.enable {
    assertions = [{
      assertion = config.aurora.speakerguardd.v2.enable;
      message = "aurora.speakerguardd.upgrade.enable switches to speakerguardd v2: set aurora.speakerguardd.v2.enable too.";
    }];
    environment.systemPackages = [ pkgs.aurora-speaker-upgrade ];
    systemd.packages = [ pkgs.aurora-speaker-upgrade ];
    systemd.services.aurora-speaker-upgrade = {
      wantedBy = [ "multi-user.target" ];
      path = [ pkgs.alsa-utils pkgs.util-linux pkgs.systemd ];
    };
  };
}
