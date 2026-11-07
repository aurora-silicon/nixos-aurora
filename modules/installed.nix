{ config, lib, pkgs, ... }:
# An installed Aurora NixOS system (the image's /etc/nixos flake imports this).
#
# - Every bootloader install (nixos-rebuild switch or boot) refreshes the ESP
#   Stage 2 exactly as update-m1n1 does on ALARM and Fedora: aura, every Apple
#   device tree of the new kernel and U-Boot, written only when it changes,
#   with the previous file kept as m1n1/boot.bin.old. Stage 1 is never written.
# - aurora-update updates the declared consumer flake's Aurora input, in one
#   command. Nothing upgrades unattended.
let
  cfg = config.aurora.stage2;
  esp = config.boot.loader.efi.efiSysMountPoint;
  # The aura build the Apple Silicon module puts at the front of Stage 2.
  aura = pkgs.m1n1.override (lib.optionalAttrs (config.boot.m1n1CustomLogo != null) {
    customLogo = config.boot.m1n1CustomLogo;
  });
  stage2Parser = pkgs.writeTextDir "stage2.py" (builtins.readFile ../scripts/stage2.py);
  # The Apple Silicon module's combined Stage 2: the same bytes the image ships
  # in m1n1/boot.bin, so an unchanged system never rewrites the ESP.
  stage2 = pkgs.runCommand "aurora-stage2" { nativeBuildInputs = [ pkgs.python3 ]; } ''
    mkdir $out
    cp ${config.system.build.m1n1} $out/boot.bin
    PYTHONPATH=${stage2Parser} python3 ${../scripts/check-stage2.py} --stage2 $out/boot.bin \
      --aura ${aura}/lib/m1n1/m1n1.bin ${lib.concatMapStringsSep " " (board: "--require-board ${lib.escapeShellArg board}") cfg.requiredBoards} \
      > $out/manifest.json
    sha256sum $out/boot.bin | cut -d' ' -f1 > $out/boot.bin.sha256
  '';
  installStage2 = pkgs.writeShellApplication {
    name = "aurora-install-stage2";
    runtimeInputs = [ pkgs.coreutils pkgs.diffutils pkgs.util-linux ];
    # writeShellApplication supplies the shebang and strict mode.
    text = lib.removePrefix "#!/usr/bin/env bash\n" (builtins.readFile ../scripts/install-stage2.sh);
  };
  update = pkgs.writeShellApplication {
    name = "aurora-update";
    runtimeInputs = [ config.nix.package pkgs.nixos-rebuild ];
    text = ''
      exec ${pkgs.python3}/bin/python3 ${../scripts/aurora-update.py} \
        --configured-input ${lib.escapeShellArg config.aurora.update.inputName} \
        ${lib.optionalString (config.aurora.update.flake != null)
          "--configured-flake ${lib.escapeShellArg config.aurora.update.flake}"} \
        ${lib.optionalString ((config.aurora.imageLayout or null) != null)
          "--factory-flake /etc/nixos#aurora"} "$@"
    '';
  };
in {
  # Remove only the upstream unchecked Stage 2 copy after merging all file
  # declarations. Other GRUB files remain available to the host. Keep this
  # exclusion when stage2.enable is false, so opting out leaves the ESP alone.
  options.boot.loader.grub.extraFiles = lib.mkOption {
    apply = files: builtins.removeAttrs files [ "m1n1/boot.bin" ];
  };
  options.aurora.stage2 = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Refresh the checked `m1n1/boot.bin` on bootloader installs, writing only
        when it changes and retaining `boot.bin.old`. False prevents automatic
        Stage 2 writes, including the upstream unchecked copy. Update commands
        remain installed; Stage 1 is never written by this module.
      '';
    };
    requiredBoards = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "j700" "j616s" "j614s" ];
      example = [ "j700" "j616s" "j614s" ];
      description = ''
        Board identifiers whose device trees must be present in the shared
        Stage 2; omit the `apple,` prefix. A missing board fails its build.
        This validates contents, not which boards are included by the kernel.
      '';
    };
  };
  options.aurora.update = {
    flake = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "/home/owner/nixos#macbook";
      description = ''
        Consumer flake updated by `aurora-update`, optionally followed by its
        NixOS configuration name. Without a selector the host name is used.
        Set this for systems maintained with direct `nixos-rebuild` commands:
        NixOS does not retain their original consumer flake reference.
        An explicit `aurora-update --flake` overrides this and remembers a
        successful local activation only for that exact system generation.
        Factory images fall back to `/etc/nixos#aurora`; other systems require
        this option or an explicit reference. Updating requires a writable
        local consumer lockfile.
      '';
    };
    inputName = lib.mkOption {
      type = lib.types.str;
      default = "aurora";
      description = "Name of the Aurora input to update in the consumer flake.";
    };
  };
  config = {
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
