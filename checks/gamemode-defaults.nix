{ pkgs, nixpkgs, makeSystem }:
let
  inherit (nixpkgs) lib;
  minimal = (makeSystem "minimal").config;
  kde = (makeSystem "kde").config;
  gnome = (makeSystem "gnome").config;
  optOut = ((makeSystem "kde").extendModules {
    modules = [ { programs.gamemode.enable = false; } ];
  }).config;
  own = ((makeSystem "kde").extendModules {
    modules = [ { programs.gamemode.settings.general.desiredgov = "performance"; } ];
  }).config;
  s = kde.programs.gamemode.settings;
in assert lib.assertMsg (kde.programs.gamemode.enable && gnome.programs.gamemode.enable)
     "GameMode must be on by default in the desktop profiles";
   assert lib.assertMsg (!minimal.programs.gamemode.enable && !(minimal.environment.etc ? "gamemode.ini"))
     "GameMode must stay off in the minimal profile";
   assert lib.assertMsg (!optOut.programs.gamemode.enable && !(optOut.environment.etc ? "gamemode.ini"))
     "programs.gamemode.enable = false must turn GameMode off";
   assert lib.assertMsg (s.general.desiredgov == "schedutil" && s.general.defaultgov == "schedutil")
     "GameMode must keep schedutil on Apple silicon";
   assert lib.assertMsg (s.cpu.pin_cores == "yes" && s.cpu.park_cores == "no")
     "GameMode must pin games to the big cores without parking";
   assert lib.assertMsg (gnome.programs.gamemode.settings.cpu.pin_cores == "yes")
     "the GNOME profile must get the same GameMode defaults";
   assert lib.assertMsg (own.programs.gamemode.settings.general.desiredgov == "performance")
     "an explicit programs.gamemode.settings value must win";
   pkgs.runCommand "aurora-gamemode-defaults-check" { } ''
     grep -qx 'desiredgov=schedutil' ${kde.environment.etc."gamemode.ini".source}
     grep -qx 'pin_cores=yes' ${kde.environment.etc."gamemode.ini".source}
     touch $out
   ''
