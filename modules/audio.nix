{ config, lib, pkgs, ... }:
{
  options.aurora.audio = {
    skipLockedControls = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Leave ALSA controls locked by another process to their owner during restore.";
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
      description = "Carry the ALSA sequencer alongside early display audio in the initrd.";
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
