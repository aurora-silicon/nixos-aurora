{ config, lib, pkgs, ... }:
# An installed Aurora NixOS system (the image's /etc/nixos flake imports this).
#
# - Every bootloader install (nixos-rebuild switch or boot) refreshes the ESP
#   Stage 2 exactly as update-m1n1 does on ALARM and Fedora: aura, the new
#   kernel's Apple device trees and U-Boot, written only when it changes, with
#   the previous file kept as .old. Every Mac gets m1n1/boot.bin with every tree
#   until aura has no monitor. Then a Mac that boots a Mach-O Stage 1 gets
#   m1n1/boot-ctxr.bin with its own board's trees, and its m1n1/boot.bin stays
#   as it is. Stage 1 is never written.
# - aurora-update takes the newest signed update of the channel /etc/nixos
#   follows, in one command. Nothing upgrades unattended.
let
  cfg = config.aurora.stage2;
  esp = config.boot.loader.efi.efiSysMountPoint;
  # The aura build the Apple Silicon module puts at the front of Stage 2.
  aura = pkgs.m1n1.override (lib.optionalAttrs (config.boot.m1n1CustomLogo != null) {
    customLogo = config.boot.m1n1CustomLogo;
  });
  # The Apple Silicon module's combined Stage 2: the same bytes the image ships
  # in m1n1/boot.bin, so an unchanged system never rewrites the ESP.
  stage2 = pkgs.runCommand "aurora-stage2" { nativeBuildInputs = [ pkgs.python3 ]; } ''
    mkdir $out
    cp ${config.system.build.m1n1} $out/boot.bin
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
    runtimeInputs = [ pkgs.coreutils pkgs.diffutils pkgs.util-linux ];
    # writeShellApplication supplies the shebang and strict mode.
    text = lib.removePrefix "#!/usr/bin/env bash\n" (builtins.readFile ../scripts/install-stage2.sh);
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
      description = "Refresh the ESP Stage 2 on every bootloader install, as update-m1n1 does.";
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
    boot.loader.grub.extraInstallCommands = lib.mkIf cfg.enable ''
      ${installStage2}/bin/aurora-install-stage2 ${stage2} ${lib.escapeShellArg esp}
    '';
    system.build.auroraStage2 = stage2;
    # The installer and update commands alone (shellchecked, no kernel build).
    system.build.auroraStage2Tools = pkgs.symlinkJoin {
      name = "aurora-stage2-tools";
      paths = [ installStage2 update ];
    };
    environment.systemPackages = [ update installStage2 ];
    # Updates are taken deliberately (aurora-update), as on ALARM and Fedora.
    system.autoUpgrade.enable = lib.mkDefault false;
  };
}
