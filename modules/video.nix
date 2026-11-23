{ config, lib, pkgs, ... }:
let
  # Only the patched plugin, not the whole of aurora-gst-plugins-good: every
  # other GStreamer plugin keeps coming from the application's own closure.
  proresGstPlugin = pkgs.runCommandLocal "aurora-gst-video4linux2" { } ''
    plugin=${pkgs.aurora-gst-plugins-good}/lib/gstreamer-1.0/libgstvideo4linux2.so
    test -f "$plugin"
    mkdir -p "$out/lib/gstreamer-1.0"
    ln -s "$plugin" "$out/lib/gstreamer-1.0/"
  '';
in
{
  options.aurora.video.proresV4l2 = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = ''
      Give applications the ProRes engine's V4L2 encoder and decoder. Installs
      aurora-ffmpeg, nixpkgs' FFmpeg with the `prores_v4l2m2m` codecs, as the
      system's `ffmpeg`, and puts the `video4linux2` plugin of
      aurora-gst-plugins-good (`v4l2proresdec`, `v4l2proresenc`) on
      `GST_PLUGIN_PATH_1_0` for every session. GStreamer scans that path
      before `GST_PLUGIN_SYSTEM_PATH_1_0`, where nixpkgs' wrappers put an
      application's own plugins, and keeps the first plugin it finds under a
      file name, so the patched plugin replaces nixpkgs' copy of the same
      plugin and nothing else. False leaves both unchanged.
    '';
  };
  config = lib.mkIf config.aurora.video.proresV4l2 {
    environment.systemPackages = [ pkgs.aurora-ffmpeg ];
    environment.sessionVariables.GST_PLUGIN_PATH_1_0 = [ "${proresGstPlugin}/lib/gstreamer-1.0" ];
  };
}
