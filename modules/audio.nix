{ config, lib, pkgs, ... }:
{
  imports = [
    (lib.mkRemovedOptionModule [ "aurora" "audio" "pipewireFixes" ]
      "The PipeWire daemon now always defaults to aurora-pipewire; set services.pipewire.package to override it.")
  ];
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
    {
      # aurora-pipewire is nixpkgs' PipeWire with the filter-graph volume and
      # latency fixes and the AirPlay sender fixes that Fedora and Arch Linux
      # ARM carry. Without it, an update that repeats the current volume or
      # mute state applies the speaker volume twice.
      services.pipewire.package = lib.mkDefault pkgs.aurora-pipewire;
    }
    (lib.mkIf config.aurora.audio.initrdSequencer {
      # availableKernelModules includes it without forcing an early load.
      boot.initrd.availableKernelModules = [ "snd-seq" ];
    })
  ];
}
