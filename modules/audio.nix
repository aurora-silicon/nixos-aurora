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
    pipewireFixes = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Run the PipeWire daemon from aurora-pipewire, nixpkgs' PipeWire with
        the filter-graph volume and latency fixes and the AirPlay sender fixes
        that Fedora and Arch Linux ARM carry. Without it, an update that repeats
        the current volume or mute state applies the speaker volume twice.
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
    (lib.mkIf config.aurora.audio.pipewireFixes {
      services.pipewire.package = lib.mkDefault pkgs.aurora-pipewire;
    })
    (lib.mkIf config.aurora.audio.initrdSequencer {
      # availableKernelModules includes it without forcing an early load.
      boot.initrd.availableKernelModules = [ "snd-seq" ];
    })
  ];
}
