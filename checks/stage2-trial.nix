{ pkgs, nixpkgs, self, imageProbe }:
let
  inherit (nixpkgs) lib;
  probe = imageProbe.config;
  disabled = (imageProbe.extendModules { modules = [ { aurora.stage2.enable = false; } ]; }).config;
  text = value: builtins.unsafeDiscardStringContext (toString value);
  commit = probe.systemd.services.aurora-stage2-commit;
  guard = probe.systemd.services.aurora-stage2-guard;
  timer = probe.systemd.timers.aurora-stage2-guard;
  trial = "/proc/device-tree/chosen/aurora,trial";
  esp = probe.boot.loader.efi.efiSysMountPoint;
  expectations = {
    "the commit runs once per boot after multi-user.target, only with an aura-try marker" =
      lib.elem "multi-user.target" commit.wantedBy && lib.elem "multi-user.target" commit.after
      && commit.unitConfig.DefaultDependencies == false && lib.elem "shutdown.target" commit.conflicts
      && commit.unitConfig.ConditionPathExists == "${esp}/aura-try"
      && commit.unitConfig.RequiresMountsFor == esp && !commit.restartIfChanged
      && commit.serviceConfig.Type == "oneshot" && commit.serviceConfig.RemainAfterExit
      && lib.hasSuffix "/bin/aurora-stage2-commit commit" (text commit.serviceConfig.ExecStart);
    "a twelve-minute guard reboots only an uncommitted trial boot" =
      lib.elem "timers.target" timer.wantedBy && timer.timerConfig.OnBootSec == "12min"
      && timer.unitConfig.ConditionPathExists == trial && guard.unitConfig.ConditionPathExists == trial
      && guard.wantedBy == [ ] && lib.hasSuffix "/bin/aurora-stage2-commit guard" (text guard.serviceConfig.ExecStart);
    "bootloader installs hand the trial the configuration being installed" =
      lib.hasInfix ''aurora-install-stage2 '' (text probe.boot.loader.grub.extraInstallCommands)
      && lib.hasInfix ''"''${1:-}"'' (text probe.boot.loader.grub.extraInstallCommands)
      && lib.hasInfix "AURORA_CONFIGURATION_LIMIT=${toString probe.boot.loader.grub.configurationLimit}"
        (text probe.boot.loader.grub.extraInstallCommands);
    "a switch checks the DT ABI generation before GRUB's menu changes" =
      lib.hasInfix "/bin/aurora-stage2 check" (text probe.system.preSwitchChecks.aurora-stage2-dt-abi or "");
    "every generation, the images' included, records its kernel's DT ABI generation from kernel/dtb-abi" =
      lib.all (c: c.boot.kernelPackages.kernel.auroraDtbAbi == lib.toInt (lib.fileContents ../kernel/dtb-abi)
        && lib.hasInfix "echo ${lib.fileContents ../kernel/dtb-abi} > $out/aurora-dtb-abi" (text c.system.systemBuilderCommands))
        ([ probe ] ++ map (system: system.config) (lib.attrValues self.nixosConfigurations));
    "aurora.stage2.enable = false leaves out the trial and its checks" =
      !(disabled.systemd.services ? aurora-stage2-commit) && !(disabled.systemd.timers ? aurora-stage2-guard)
      && !(disabled.system.preSwitchChecks ? aurora-stage2-dt-abi)
      && !(lib.hasInfix "aurora-install-stage2" disabled.boot.loader.grub.extraInstallCommands);
  };
in pkgs.runCommand "aurora-stage2-trial-evaluation" {
  failures = lib.concatStringsSep "\n" (lib.attrNames (lib.filterAttrs (_: met: !met) expectations));
  tested = pkgs.aurora-stage2;
} ''
  if [[ -n "$failures" ]]; then printf '%s\n' "$failures" >&2; exit 1; fi
  touch $out
''
