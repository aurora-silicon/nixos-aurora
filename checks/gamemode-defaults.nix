{ pkgs, nixpkgs, makeSystem }:
let
  inherit (nixpkgs) lib;
  off = (makeSystem "minimal").config;
  on = ((makeSystem "minimal").extendModules {
    modules = [ { programs.gamemode.enable = true; } ];
  }).config;
  own = ((makeSystem "minimal").extendModules {
    modules = [ { programs.gamemode.enable = true; programs.gamemode.settings.general.desiredgov = "performance"; } ];
  }).config;
  s = on.programs.gamemode.settings;
in assert lib.assertMsg (!off.programs.gamemode.enable && !(off.environment.etc ? "gamemode.ini"))
     "GameMode must stay off unless asked for";
   assert lib.assertMsg (s.general.desiredgov == "schedutil" && s.general.defaultgov == "schedutil")
     "GameMode must keep schedutil on Apple silicon";
   assert lib.assertMsg (s.cpu.pin_cores == "yes" && s.cpu.park_cores == "no")
     "GameMode must pin games to the big cores without parking";
   assert lib.assertMsg (own.programs.gamemode.settings.general.desiredgov == "performance")
     "an explicit programs.gamemode.settings value must win";
   pkgs.runCommand "aurora-gamemode-defaults-check" { } ''
     grep -qx 'desiredgov=schedutil' ${on.environment.etc."gamemode.ini".source}
     grep -qx 'pin_cores=yes' ${on.environment.etc."gamemode.ini".source}
     touch $out
   ''
