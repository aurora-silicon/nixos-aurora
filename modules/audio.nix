{ config, lib, pkgs, ... }:
let
  ucmDir = "${pkgs.alsa-ucm-conf-asahi}/share/alsa/ucm2";
  speakerStack = config.aurora.speakers.stack;
in {
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
  options.aurora.speakers = {
    stack = lib.mkOption {
      type = lib.types.enum [ "sgv2" "speakersafetyd" ];
      default = "sgv2";
      description = ''
        Active Apple Silicon speaker protection stack. The default (`sgv2`)
        runs speakerguardd v2 with aurora-speaker-upgrade and installs no
        legacy speaker protection daemon or Asahi speaker DSP graphs. Set
        to `speakersafetyd` (or run `sudo aurora-speaker-stack select
        speakersafetyd`) as an explicit user opt-out that survives upgrades.
      '';
    };
  };
  config = lib.mkMerge [
    (lib.mkIf config.aurora.audio.skipLockedControls {
      nixpkgs.overlays = [ (final: _: { alsa-utils = final.aurora-alsa-utils; }) ];
      environment.systemPackages = [ pkgs.alsa-utils ];
    })
    {
      # Manage PipeWire/WirePlumber/UCM directly so nixos-apple-silicon's
      # setupAsahiSound does not pull speakersafetyd into the default system.
      hardware.asahi.setupAsahiSound = lib.mkDefault false;
      # aurora-pipewire is nixpkgs' PipeWire with the filter-graph volume and
      # latency fixes and the AirPlay sender fixes that Fedora and Arch Linux
      # ARM carry. Without it, an update that repeats the current volume or
      # mute state applies the speaker volume twice.
      services.pipewire.package = lib.mkDefault pkgs.aurora-pipewire;
      environment.systemPackages = [ pkgs.aurora-speaker-stack ];
    }
    (lib.mkIf (!config.hardware.asahi.setupAsahiSound) {
      services.pulseaudio.enable = false;
      security.rtkit.enable = true;
      services.pipewire = {
        enable = true;
        alsa.enable = true;
        pulse.enable = true;
        configPackages = [ pkgs.asahi-audio ];
        wireplumber = {
          enable = true;
          configPackages = [ pkgs.asahi-audio ];
        };
      };
      environment.variables.ALSA_CONFIG_UCM2 = ucmDir;
      systemd.user.services.pipewire.environment.ALSA_CONFIG_UCM2 = ucmDir;
      systemd.user.services.wireplumber.environment.ALSA_CONFIG_UCM2 = ucmDir;
      systemd.services.pipewire.environment.ALSA_CONFIG_UCM2 = ucmDir;
      systemd.services.wireplumber.environment.ALSA_CONFIG_UCM2 = ucmDir;
    })
    (lib.mkIf (speakerStack == "speakersafetyd") {
      systemd.packages = [ pkgs.speakersafetyd ];
      services.udev.packages = [ pkgs.speakersafetyd ];
      environment.etc."aurora/speaker-stack.conf".text = "stack=speakersafetyd\n";
    })
    (lib.mkIf config.aurora.audio.initrdSequencer {
      # availableKernelModules includes it without forcing an early load.
      boot.initrd.availableKernelModules = [ "snd-seq" ];
    })
  ];
}
