{ pkgs, nixpkgs, makeSystem }:
let
  inherit (nixpkgs) lib;
  # Same unit as aurora-platform's power/aurora-power-modes.service, which
  # Fedora and ALARM enable by preset beside aurora-power-budget.
  kde = (makeSystem "kde").config;
  gnome = (makeSystem "gnome").config;
  minimal = (makeSystem "minimal").config;
  extend = module: ((makeSystem "kde").extendModules { modules = [ module ]; }).config;
  noBudget = extend { aurora.powerBudget.enable = false; };
  optOut = extend { systemd.services.aurora-power-modes.enable = false; };
  own = extend { environment.etc."aurora/power-modes.conf".text = "low_power_mode = battery\n"; };
  unitOf = config: config.systemd.units."aurora-power-modes.service";
  s = kde.systemd.services.aurora-power-modes;
  budget = kde.systemd.services.aurora-power-budget;
  conf = config: config.environment.etc."aurora/power-modes.conf";
  package = pkgs.aurora-power-budget;
in assert lib.assertMsg (lib.all (c: c.aurora.powerBudget.enable == c.services.power-profiles-daemon.enable
       && (c.systemd.services ? aurora-power-modes) == c.aurora.powerBudget.enable
       && (c.environment.etc ? "aurora/power-modes.conf") == c.aurora.powerBudget.enable) [ kde gnome minimal ])
     "aurora-power-modes and its configuration must come with aurora-power-budget in every profile";
   assert lib.assertMsg (lib.all (c: (unitOf c).enable && (unitOf c).wantedBy == [ "multi-user.target" ]) [ kde gnome ])
     "aurora-power-modes must be on in the desktop profiles, wanted by multi-user.target as its preset intends";
   assert lib.assertMsg (s.unitConfig.ConditionPathExists == "/sys/firmware/devicetree/base/cpus")
     "aurora-power-modes must run on device tree boots only";
   assert lib.assertMsg (s.after == [ "tuned-ppd.service" "power-profiles-daemon.service" ])
     "aurora-power-modes must start after the profile daemon";
   assert lib.assertMsg (lib.elem "aurora-power-modes.service" kde.systemd.services.aurora-power-defaults.before)
     "the power defaults must be in place before aurora-power-modes records its boot baseline";
   assert lib.assertMsg (lib.hasSuffix "/libexec/aurora/aurora-power-modes" s.serviceConfig.ExecStart
       && lib.hasPrefix (dirOf budget.serviceConfig.ExecStart) s.serviceConfig.ExecStart)
     "aurora-power-modes must run from the aurora-power-budget package";
   assert lib.assertMsg (builtins.removeAttrs s.serviceConfig [ "ExecStart" ] == {
       Restart = "on-failure";
       RestartSec = 5;
       RuntimeDirectory = "aurora-power-modes";
       RuntimeDirectoryPreserve = "restart";
       NoNewPrivileges = true;
       PrivateTmp = true;
       ProtectHome = true;
       ProtectSystem = "full";
     })
     "aurora-power-modes must keep the service settings of the aurora-platform unit";
   assert lib.assertMsg (lib.elem kde.systemd.package s.path)
     "aurora-power-modes needs busctl to follow the profile daemon";
   assert lib.assertMsg (lib.hasSuffix "/etc/aurora/power-modes.conf" (toString (conf kde).source)
       && lib.hasPrefix (toString package) (toString (conf kde).source))
     "/etc/aurora/power-modes.conf must be the package's commented default";
   assert lib.assertMsg ((conf own).text == "low_power_mode = battery\n"
       && !(lib.hasPrefix (toString package) (toString (conf own).source)))
     "an explicit environment.etc text must replace the default configuration";
   assert lib.assertMsg (!(noBudget.systemd.services ? aurora-power-modes)
       && !(noBudget.environment.etc ? "aurora/power-modes.conf"))
     "aurora.powerBudget.enable = false must leave aurora-power-modes out";
   assert lib.assertMsg (!(unitOf optOut).enable && optOut.systemd.services.aurora-power-budget.enable)
     "systemd.services.aurora-power-modes.enable = false must keep the budget without the other legs";
   pkgs.runCommand "aurora-power-modes-check" { } ''
     unit=${(unitOf kde).unit}/aurora-power-modes.service
     grep -qx 'ConditionPathExists=/sys/firmware/devicetree/base/cpus' $unit
     grep -qx 'After=tuned-ppd.service power-profiles-daemon.service' $unit
     grep -qx 'ExecStart=${package}/libexec/aurora/aurora-power-modes' $unit
     grep -qx 'RuntimeDirectoryPreserve=restart' $unit
     test -x ${package}/libexec/aurora/aurora-power-modes
     # Every line of the default configuration is a comment, so the defaults apply.
     conf=${(conf kde).source}
     test -s $conf
     ! grep -qv -e '^#' -e '^$' $conf
     grep -q "${package}/share/doc/aurora-power-budget/README.md" $conf
     test -f ${package}/share/doc/aurora-power-budget/README.md
     ! grep -rq /usr/share/doc $conf
     touch $out
   ''
