{ pkgs, nixpkgs, makeSystem }:
let
  inherit (nixpkgs) lib;
  # Same unit as Fedora's aurora-platform-core and ALARM's aurora-system-fixes.
  unitOf = config: config.systemd.units."aurora-power-defaults.service";
  kde = (makeSystem "kde").config;
  minimal = (makeSystem "minimal").config;
  optOut = ((makeSystem "kde").extendModules {
    modules = [ { systemd.services.aurora-power-defaults.enable = false; } ];
  }).config;
  s = kde.systemd.services.aurora-power-defaults;
  exec = s.serviceConfig.ExecStart;
in assert lib.assertMsg (lib.all (c: (unitOf c).enable && lib.elem "sysinit.target" (unitOf c).wantedBy) [ kde minimal ])
     "the power defaults must be on in every profile, wanted by sysinit.target";
   assert lib.assertMsg (s.unitConfig.ConditionFirmware == "device-tree-compatible(apple,arm-platform)")
     "the power defaults must apply on every Apple silicon Mac and nowhere else";
   assert lib.assertMsg (lib.elem "aurora-power-modes.service" s.before && lib.elem "sysinit.target" s.before)
     "the power defaults must be in place before aurora-power-modes records its boot baseline";
   assert lib.assertMsg (s.serviceConfig.Type == "oneshot" && s.serviceConfig.RemainAfterExit)
     "the power defaults are a oneshot that stays active";
   assert lib.assertMsg (lib.length exec == 2
       && lib.hasPrefix "-" (lib.elemAt exec 0)
       && lib.hasSuffix "-c 'echo powersupersave > /sys/module/pcie_aspm/parameters/policy'" (lib.elemAt exec 0)
       && lib.hasSuffix "/bin/sysctl -q -w kernel.sched_util_clamp_min_rt_default=0" (lib.elemAt exec 1))
     "ASPM powersupersave (allowed to fail under pcie_aspm=off), then no realtime utilization floor";
   assert lib.assertMsg (!(unitOf optOut).enable)
     "systemd.services.aurora-power-defaults.enable = false must keep the kernel's defaults";
   pkgs.runCommand "aurora-power-defaults-check" { } ''
     unit=${(unitOf kde).unit}/aurora-power-defaults.service
     grep -qx 'ConditionFirmware=device-tree-compatible(apple,arm-platform)' $unit
     grep -qx 'DefaultDependencies=false' $unit
     grep -q '^Before=.*aurora-power-modes.service' $unit
     grep -q "^ExecStart=-.* -c 'echo powersupersave > /sys/module/pcie_aspm/parameters/policy'$" $unit
     grep -q '^ExecStart=.*/bin/sysctl -q -w kernel.sched_util_clamp_min_rt_default=0$' $unit
     touch $out
   ''
