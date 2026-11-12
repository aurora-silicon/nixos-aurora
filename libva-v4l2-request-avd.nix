{ lib, stdenv, src, version, portabilityPatch, extraPatches ? [ ], meson, ninja, pkg-config
, python3, libva, libdrm, linuxHeaders }:
stdenv.mkDerivation {
  pname = "libva-v4l2-request-avd";
  inherit version src;

  patches = [ portabilityPatch ] ++ extraPatches;
  strictDeps = true;
  nativeBuildInputs = [ meson ninja pkg-config python3 ];
  buildInputs = [ libva libdrm linuxHeaders ];

  mesonFlags = [
    "-Ddriverdir=${placeholder "out"}/lib/dri"
    "-Dstrip=false"
    "-Dcodec_h264=enabled"
    "-Dcodec_hevc=enabled"
    "-Dcodec_vp9=enabled"
    "-Dcodec_av1=enabled"
  ];

  doCheck = true;
  checkPhase = ''
    runHook preCheck
    meson test --print-errorlogs --num-processes "$NIX_BUILD_CORES"
    runHook postCheck
  '';

  postInstall = ''
    ln -s v4l2_request_drv_video.so "$out/lib/dri/asahi_drv_video.so"
    # Aurora kernels name the AGX render node driver "aurora".
    ln -s v4l2_request_drv_video.so "$out/lib/dri/aurora_drv_video.so"
  '';

  doInstallCheck = true;
  installCheckPhase = ''
    test -f "$out/lib/dri/v4l2_request_drv_video.so"
    test -L "$out/lib/dri/asahi_drv_video.so"
    test "$(readlink "$out/lib/dri/asahi_drv_video.so")" = v4l2_request_drv_video.so
    test -L "$out/lib/dri/aurora_drv_video.so"
    test "$(readlink "$out/lib/dri/aurora_drv_video.so")" = v4l2_request_drv_video.so
  '';

  meta = {
    description = "VA-API driver for the AVD V4L2 Request decoder";
    homepage = "https://github.com/omacom/libva-v4l2_request";
    license = lib.licenses.gpl3Plus;
    platforms = [ "aarch64-linux" ];
  };
}
