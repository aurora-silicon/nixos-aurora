{ config, lib, pkgs, ... }:
{
  options.aurora.audio = {
    skipLockedControls = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Leave ALSA controls locked by another process to their owner during restore.";
    };
    initrdSequencer = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Carry the ALSA sequencer alongside early display audio in the initrd.";
    };
  };
  config = lib.mkMerge [
    (lib.mkIf config.aurora.audio.skipLockedControls {
      nixpkgs.overlays = [ (final: _: { alsa-utils = final.aurora-alsa-utils; }) ];
      environment.systemPackages = [ pkgs.alsa-utils ];
    })
    (lib.mkIf config.aurora.audio.initrdSequencer {
      # availableKernelModules includes it without forcing an early load.
      boot.initrd.availableKernelModules = [ "snd-seq" ];
    })
  ];
}
