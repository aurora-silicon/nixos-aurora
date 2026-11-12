# Hardware video encoding (H.264, HEVC) through VA-API on Apple AVE.
# Off by default: it needs a kernel with the SoC's apple-ave variant and
# device tree, and an aura that hands the encoder its firmware.
{ config, lib, pkgs, ... }:
let cfg = config.aurora.videoEncoder; in {
  options.aurora.videoEncoder.enable = lib.mkEnableOption ''
    VA-API hardware video encoding on the Apple AVE. This installs the AVE
    VA driver and replaces the aurora_drv_video.so alias with a VA driver that
    serves both AVD decode and AVE encode'';
  config = lib.mkIf cfg.enable {
    hardware.graphics.extraPackages = [
      pkgs.aurora-ave-vaapi
      # Wins the aurora_drv_video.so name over libva-v4l2-request-avd's alias.
      (lib.hiPrio pkgs.aurora-va-dispatch)
    ];
  };
}
