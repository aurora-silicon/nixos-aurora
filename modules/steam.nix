{ config, lib, pkgs, ... }:
{
  # Steam's upstream NixOS module assumes an x86 host. The native ARM64
  # client uses the host's 64-bit graphics/audio; FEX carries guest libraries
  # in its own rootfs instead of NixOS's x86-only 32-bit driver environment.
  config = lib.mkIf (config.programs.steam.enable && pkgs.stdenv.hostPlatform.isAarch64) {
    hardware.graphics.enable32Bit = lib.mkForce false;
    services.pipewire.alsa.support32Bit = lib.mkForce false;
    services.pulseaudio.support32Bit = lib.mkForce false;
    assertions = [ {
      assertion = !config.programs.steam.extest.enable;
      message = "Steam's extest injection library is x86-only; disable programs.steam.extest on ARM64.";
    } ];
  };
}
