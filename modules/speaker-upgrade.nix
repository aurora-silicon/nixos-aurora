{ config, lib, pkgs, ... }:
{
  # aurora-speaker-upgrade moves a Mac's speakers to speakerguardd v2, the only
  # speaker stack, with its own tuning. The option
  # defaults to false; the Aurora platform turns it on (modules/platform.nix).
  # Enabled, its unit runs at every boot (run --at-boot): it switches only on
  # a passing self-check and does not retry a refusal until the kernel,
  # speakerguardd or the tool changes.
  options.aurora.speakerguardd.upgrade.enable = lib.mkOption {
    type = lib.types.bool;
    default = false;
    description = "Install aurora-speaker-upgrade and run it at boot: it moves the speakers to speakerguardd v2 when this Mac's own tuning passes the silent self-check (needs aurora.speakerguardd.v2.enable). A refused Mac keeps its speakers at the kernel's floor (speakersafetyd and speakerguardd 0.1 are no longer shipped). The Aurora platform turns it on.";
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
