{ config, lib, pkgs, ... }:
{
  # aurora-speaker-upgrade moves a Mac from the legacy speaker protection to
  # speakerguardd v2 with its own tuning (and back with --revert). The option
  # defaults to false; the Aurora platform turns it on (modules/platform.nix).
  # Enabled, its unit runs at every boot (run --at-boot): it switches only on
  # a passing self-check and does not retry a refusal until the kernel or
  # speakerguardd changes (speakerguardd#125).
  options.aurora.speakerguardd.upgrade.enable = lib.mkOption {
    type = lib.types.bool;
    default = false;
    description = "Install aurora-speaker-upgrade and run it at boot: it moves the speakers to speakerguardd v2 when this Mac's own tuning passes the silent self-check (needs aurora.speakerguardd.v2.enable).";
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
