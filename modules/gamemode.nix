{ config, lib, ... }:
# GameMode defaults for Apple silicon, the same as aurora-platform's
# power/gamemode.ini (Fedora and ALARM install that file as
# /etc/gamemode.ini). Games started with GameMode run on the P cores
# (GameMode picks the CPUs within 10 % of the top cpuinfo_max_freq and
# skips pinning below four, so the A18 Pro is left alone), and the
# governor stays schedutil instead of GameMode's default "performance".
# Each value is a default: programs.gamemode.settings still overrides it.
# GameMode itself is on by default in the KDE and GNOME profiles, as on
# Fedora and ALARM desktops, and Aurora's `steam` registers every game with
# it; programs.gamemode.enable = false turns it off.
{
  config = lib.mkMerge [
    { programs.gamemode.enable = lib.mkDefault (config.aurora.desktop != "minimal"); }
    (lib.mkIf config.programs.gamemode.enable {
      programs.gamemode.settings = {
        general = {
          desiredgov = lib.mkDefault "schedutil";
          defaultgov = lib.mkDefault "schedutil";
        };
        cpu = {
          pin_cores = lib.mkDefault "yes";
          park_cores = lib.mkDefault "no";
        };
      };
    })
  ];
}
