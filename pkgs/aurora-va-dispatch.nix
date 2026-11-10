# One VA driver for decode and encode: libva and Chrome load a single VA driver
# per process, so this loads libva-v4l2-request (AVD decode) and
# aurora-ave-vaapi (AVE encode) and routes each call by object ID and usage
# (see j713_dispatch.c). It is installed as aurora_drv_video.so, the name
# libva picks for the "aurora" render node. Host tests run in the build.
{ lib, stdenv, src, version, gnumake, libva, libvaV4l2RequestAvd, aurora-ave-vaapi }:
let
  dec = "${libvaV4l2RequestAvd}/lib/dri/v4l2_request_drv_video.so";
  enc = "${aurora-ave-vaapi}/lib/dri/ave_drv_video.so";
in stdenv.mkDerivation {
  pname = "aurora-va-dispatch";
  inherit version src;
  setSourceRoot = ''sourceRoot=$(echo */va-dispatch)'';
  strictDeps = true;
  nativeBuildInputs = [ gnumake ];
  buildInputs = [ libva ];
  makeFlags = [ "DEC=${dec}" "ENC=${enc}" "CC=${stdenv.cc.targetPrefix}cc" ];
  doCheck = true;
  checkTarget = "check";
  installPhase = ''
    runHook preInstall
    install -Dm755 j713_drv_video.so $out/lib/dri/aurora_drv_video.so
    runHook postInstall
  '';
  doInstallCheck = true;
  installCheckPhase = ''
    test -e ${dec} && test -e ${enc}
  '';
  meta = {
    description = "VA-API driver routing AVD decode and AVE encode through one display";
    homepage = "https://github.com/EdupugantiAkhil/aurora-ave-vaapi";
    license = lib.licenses.mit;
    platforms = [ "aarch64-linux" ];
  };
}
