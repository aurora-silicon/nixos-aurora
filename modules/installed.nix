{ config, lib, pkgs, ... }:
# An installed Aurora NixOS system (the image's /etc/nixos flake imports this).
#
# - Every bootloader install (nixos-rebuild switch or boot) refreshes the ESP
#   Stage 2 as update-m1n1 does on ALARM and Fedora: aura, the new kernel's
#   Apple device trees and U-Boot, written only when it changes. Every Mac gets
#   m1n1/boot.bin with every tree until aura has no monitor. Then a Mac that
#   boots a Mach-O Stage 1 gets m1n1/boot-ctxr.bin with its own board's trees,
#   and its m1n1/boot.bin stays as it is. Stage 1 is never written.
# - With aura Stage 1 1.0.0b4 or later the new file is a trial: it is staged as
#   <name>.next and armed as aura's one-shot aura-try, and
#   aurora-stage2-commit.service makes it live only after a trial boot passes
#   its device-tree checks; a guard timer reboots a trial that was not
#   committed. Older Stage 1 gets the file directly, the previous one kept as
#   .old. The logic is fedora-aurora's (stage2/, docs/updates.md).
# - Device trees whose DT ABI generation a configuration GRUB lists cannot boot
#   are refused before the switch, and again at install and commit time.
# - aurora-update takes the newest signed update of the channel /etc/nixos
#   follows, in one command. Nothing upgrades unattended.
let
  cfg = config.aurora.stage2;
  esp = config.boot.loader.efi.efiSysMountPoint;
  # The aura build the Apple Silicon module puts at the front of Stage 2.
  aura = pkgs.m1n1.override (lib.optionalAttrs (config.boot.m1n1CustomLogo != null) {
    customLogo = config.boot.m1n1CustomLogo;
  });
  # The DT ABI generation of this system's kernel (kernel/dtb-abi). A kernel
  # that does not declare one is generation 0, as on Fedora.
  dtbAbi = config.boot.kernelPackages.kernel.auroraDtbAbi or 0;
  configurationLimit = toString config.boot.loader.grub.configurationLimit;
  # The Apple Silicon module's combined Stage 2: the same bytes the image ships
  # in m1n1/boot.bin, so an unchanged system never rewrites the ESP.
  stage2 = pkgs.runCommand "aurora-stage2" { nativeBuildInputs = [ pkgs.python3 ]; } ''
    mkdir $out
    cp ${config.system.build.m1n1} $out/boot.bin
    # The trial checks the device trees that follow aura.
    ln -s ${aura}/lib/m1n1/m1n1.bin $out/aura.bin
    echo ${toString dtbAbi} > $out/dtb-abi
    python3 ${../scripts/check-stage2.py} --stage2 $out/boot.bin \
      --aura ${aura}/lib/m1n1/m1n1.bin ${lib.concatMapStringsSep " " (board: "--require-board ${board}") cfg.requiredBoards} \
      > $out/manifest.json
    sha256sum $out/boot.bin | cut -d' ' -f1 > $out/boot.bin.sha256
    if [[ -e ${aura}/share/aura/monitor-free ]]; then
      touch $out/monitor-free
      ${pkgs.runtimeShell} ${../scripts/build-ctxr-stage2.sh} ${../scripts/check-stage2.py} \
        ${../scripts/prepare-stage2.py} ${../scripts/prepare-ctxr-stage2.py} \
        $out/boot.bin ${aura}/lib/m1n1/m1n1.bin $out/ctxr
    fi
  '';
  installStage2 = pkgs.writeShellApplication {
    name = "aurora-install-stage2";
    runtimeInputs = [ pkgs.coreutils pkgs.util-linux pkgs.aurora-stage2 ];
    # writeShellApplication supplies the shebang and strict mode.
    text = lib.removePrefix "#!/usr/bin/env bash\n" (builtins.readFile ../scripts/install-stage2.sh);
  };
  # The boot-time side of a trial: commit (the default) or guard.
  commit = pkgs.writeShellApplication {
    name = "aurora-stage2-commit";
    runtimeInputs = [ pkgs.coreutils pkgs.util-linux pkgs.aurora-stage2 ];
    text = ''
      mode=''${1:-commit}
      esp=${lib.escapeShellArg esp}
      if ! mountpoint -q "$esp"; then
        echo "aurora-stage2-commit: $esp is not mounted" >&2
        exit 1
      fi
      ESP_ROOT=$esp
      ESP_DEVICE=$(findmnt -n -o SOURCE --mountpoint "$esp" | tail -n 1)
      ESP_FSTYPE=$(findmnt -n -o FSTYPE --mountpoint "$esp" | tail -n 1)
      # bootchain.py takes m1n1/boot-ctxr.bin instead on a Mac that boots it.
      TARGET=$esp/m1n1/boot.bin
      AURORA_MONITOR_FREE_MARKER=${aura}/share/aura/monitor-free
      AURORA_CONFIGURATION_LIMIT=${configurationLimit}
      export ESP_ROOT ESP_DEVICE ESP_FSTYPE TARGET AURORA_MONITOR_FREE_MARKER AURORA_CONFIGURATION_LIMIT
      exec aurora-stage2 "$mode"
    '';
  };
  update = pkgs.writeShellApplication {
    name = "aurora-update";
    runtimeInputs = [ config.nix.package pkgs.coreutils ];
    text = ''
      # Take the newest signed update of the channel /etc/nixos follows.
      if [[ $(id -u) != 0 ]]; then
        echo 'aurora-update: run it with sudo' >&2
        exit 1
      fi
      nix flake update aurora --flake /etc/nixos
      nixos-rebuild switch --flake /etc/nixos#aurora "$@"
    '';
  };
in {
  options.aurora.stage2 = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Refresh the ESP Stage 2 on every bootloader install, as update-m1n1 does, and commit Stage 2 trials.";
    };
    requiredBoards = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "j700" "j616s" "j614s" ];
      description = "Boards whose device trees the one shared Stage 2 must carry.";
    };
  };
  config = {
    # An aura without the monitor moves the kernel into the CTXR window, and only
    # a kernel built with CONFIG_ARM64_CTXR_EXECMEM keeps its code inside it. This
    # checks the kernel this system boots, so an overridden kernel is checked too.
    assertions = [{
      assertion = !(aura.auroraMonitorFree or false)
        || (config.boot.kernelPackages.kernel.auroraCtxrExecmem or false);
      message = "This aura has no monitor, so the kernel needs CONFIG_ARM64_CTXR_EXECMEM=y "
        + "(kernelCtxrExecmem in overlay.nix, with a kernel pin that has it).";
    }];
    # The Apple Silicon module would copy its Stage 2 over the ESP file on
    # every install without a backup or checks; Aurora installs it below.
    boot.loader.grub.extraFiles = lib.mkForce { };
    # install-grub.sh passes the configuration it makes the default as $1.
    boot.loader.grub.extraInstallCommands = lib.mkIf cfg.enable ''
      AURORA_CONFIGURATION_LIMIT=${configurationLimit} \
        ${installStage2}/bin/aurora-install-stage2 ${stage2} ${lib.escapeShellArg esp} "''${1:-}"
    '';
    # Refuse device trees a listed configuration cannot boot before GRUB's menu
    # changes; the install step checks again.
    system.preSwitchChecks.aurora-stage2-dt-abi = lib.mkIf cfg.enable ''
      case "$2" in
        switch|boot)
          AURORA_STAGE2_DIR=${stage2} ESP_ROOT=${lib.escapeShellArg esp} AURORA_TOPLEVEL="$1" \
            AURORA_CONFIGURATION_LIMIT=${configurationLimit} ${pkgs.aurora-stage2}/bin/aurora-stage2 check
          ;;
      esac
    '';
    # Units as fedora-aurora ships them. The commit runs once per boot, after
    # multi-user.target and only with an aura-try marker on the ESP.
    systemd.services.aurora-stage2-commit = lib.mkIf cfg.enable {
      description = "Commit a successful Aurora Stage 2 trial";
      wantedBy = [ "multi-user.target" ];
      after = [ "local-fs.target" "multi-user.target" ];
      before = [ "shutdown.target" ];
      conflicts = [ "shutdown.target" ];
      unitConfig = {
        # Avoid the target's implicit ordering before its wanted services.
        DefaultDependencies = false;
        RequiresMountsFor = esp;
        ConditionPathExists = "${esp}/aura-try";
      };
      restartIfChanged = false;
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = "${commit}/bin/aurora-stage2-commit commit";
      };
    };
    systemd.services.aurora-stage2-guard = lib.mkIf cfg.enable {
      description = "Return an uncommitted Aurora trial to the configured Stage 2";
      unitConfig = {
        ConditionPathExists = "/proc/device-tree/chosen/aurora,trial";
        RequiresMountsFor = esp;
      };
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${commit}/bin/aurora-stage2-commit guard";
      };
    };
    systemd.timers.aurora-stage2-guard = lib.mkIf cfg.enable {
      description = "Limit an uncommitted Aurora Stage 2 trial to twelve minutes";
      wantedBy = [ "timers.target" ];
      unitConfig.ConditionPathExists = "/proc/device-tree/chosen/aurora,trial";
      timerConfig = {
        OnBootSec = "12min";
        AccuracySec = "10s";
      };
    };
    system.build.auroraStage2 = stage2;
    # The installer, trial and update commands alone (shellchecked and tested,
    # no kernel build).
    system.build.auroraStage2Tools = pkgs.symlinkJoin {
      name = "aurora-stage2-tools";
      paths = [ installStage2 commit update pkgs.aurora-stage2 ];
    };
    environment.systemPackages = [ update installStage2 ];
    # Updates are taken deliberately (aurora-update), as on ALARM and Fedora.
    system.autoUpgrade.enable = lib.mkDefault false;
  };
}
