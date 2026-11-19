{ config, lib, pkgs, ... }:
{
  # aurora-speaker-upgrade moves a Mac from the legacy speaker protection to
  # speakerguardd v2 with its own tuning (and back with --revert). Off by
  # default; even when enabled only the tool and its units are installed:
  # nothing runs until `sudo aurora-speaker-upgrade` (or the unit) is started.
  options.aurora.speakerguardd.upgrade.enable = lib.mkOption {
    type = lib.types.bool;
    default = false;
    description = "Install aurora-speaker-upgrade (the legacy-to-speakerguardd-v2 upgrade tool); it never runs by itself.";
  };
  config = lib.mkIf config.aurora.speakerguardd.upgrade.enable {
    environment.systemPackages = [ pkgs.aurora-speaker-upgrade ];
    systemd.packages = [ pkgs.aurora-speaker-upgrade ];
  };
}
