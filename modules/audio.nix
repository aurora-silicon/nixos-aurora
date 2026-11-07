{ config, lib, pkgs, ... }:
{
  options.aurora.audio = {
    skipLockedControls = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Select and install Aurora's ALSA utilities, whose restore skips controls
        locked by another process. False leaves ALSA utility selection unchanged.
      '';
    };
    initrdSequencer = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Add `snd-seq` to the modules available in the initrd for early display
        audio. This includes the module without forcing an early load; false
        omits Aurora's additional entry.
      '';
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
