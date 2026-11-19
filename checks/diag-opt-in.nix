{ pkgs, nixpkgs, makeSystem }:
let
  inherit (nixpkgs) lib;
  off = (makeSystem "minimal").config;
  on = ((makeSystem "minimal").extendModules {
    modules = [ { aurora.diag.enable = true; } ];
  }).config;
  pkg = on.aurora.diag.package;
in assert lib.assertMsg (!off.aurora.diag.enable
     && !(lib.elem pkgs.aurora-diag off.environment.systemPackages))
     "aurora-diag must stay off unless asked for";
   assert lib.assertMsg (pkg.pname == "aurora-diag" && lib.elem pkg on.environment.systemPackages)
     "aurora.diag.enable = true must install aurora-diag";
   pkgs.runCommand "aurora-diag-package-check" { } ''
     p=${pkgs.aurora-diag}
     test -x $p/bin/aurora-diag
     test -x $p/bin/aurora-panic-log
     test -f $p/share/aurora-diag/aurora_diag/cli.py
     test -f $p/share/aurora-diag/aurora_diag/macos_baseline.json
     test -f $p/share/applications/org.aurorasilicon.Diag.desktop
     test -f $p/share/licenses/aurora-diag/LICENSE
     touch $out
   ''
