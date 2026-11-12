# ave_drv_video.so: VA-API H.264/HEVC encoder for the Apple AVE (apple-ave
# V4L2 driver). Host tests run in the build; no device is opened.
{ lib, stdenv, src, version, meson, ninja, pkg-config, libva, libdrm }:
stdenv.mkDerivation {
  pname = "aurora-ave-vaapi";
  inherit version src;
  # fetchurl gives a tarball whose root is the archive_root, not "source".
  setSourceRoot = ''sourceRoot=$(echo */ave-vaapi)'';
  strictDeps = true;
  nativeBuildInputs = [ meson ninja pkg-config ];
  buildInputs = [ libva libdrm ];
  doCheck = true;
  meta = {
    description = "VA-API encoder driver for the Apple AVE video encoder";
    homepage = "https://github.com/EdupugantiAkhil/aurora-ave-vaapi";
    license = lib.licenses.mit;
    platforms = [ "aarch64-linux" ];
  };
}
