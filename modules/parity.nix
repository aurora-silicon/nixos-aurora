{ config, pkgs, ... }:
let pins = builtins.fromJSON (builtins.readFile ../sources.json);
in {
  # The image checker follows these store paths inside the finished root.
  # Their string contexts also retain every graphics payload in the closure.
  environment.etc."aurora/parity.json".text = builtins.toJSON {
    schema = 1;
    mesaCommit = pins.mesa-aurora.commit;
    kernelCommit = pins.kernel-aurora.commit;
    audioCommit = pins.aurora-audio.commit;
    ucmCommit = pins.alsa-ucm-conf-aurora.commit;
    kernel = toString config.boot.kernelPackages.kernel;
    mesa = toString pkgs.mesa;
    alsaUtils = if config.aurora.audio.skipLockedControls then toString pkgs.alsa-utils else null;
    audio = toString pkgs.asahi-audio;
    ucm = toString pkgs.alsa-ucm-conf-asahi;
    fexMesa = if config.aurora.fexMesa.enable then toString config.aurora.fexMesa.package else null;
    flatpakGL = if config.aurora.flatpak.enable then toString config.aurora.flatpak.package else null;
    avdFirmware = toString pkgs.aurora-avd-firmware;
    defaults = {
      inherit (config.aurora.audio) skipLockedControls initrdSequencer;
      malcontentSignal = config.aurora.systemFixes.malcontentSignal;
      flatpakGL = config.aurora.flatpak.enable;
      fexMesa = config.aurora.fexMesa.enable;
    };
  };
}
