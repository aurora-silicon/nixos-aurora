{ lib, stdenv, meson, ninja, pkg-config, pipewire, coreutils, src, pin }:
stdenv.mkDerivation {
  pname = "aurora-camera-denoise";
  inherit (pin) version;
  inherit src;
  nativeBuildInputs = [ meson ninja pkg-config ];
  buildInputs = [ pipewire ];
  mesonFlags = [
    "-Ddaemon=enabled"
    # The optional Vulkan temporal backend stays out, as on Fedora and Arch.
    "-Dgpu=disabled"
    "-Dsysconfdir=/etc"
    "-Dsystemduserunitdir=${placeholder "out"}/lib/systemd/user"
  ];
  doCheck = true;
  postInstall = ''
    substituteInPlace $out/lib/systemd/user/aurora-camera-denoise.service \
      --replace-fail "ExecReload=/bin/kill" "ExecReload=${coreutils}/bin/kill"
  '';
  passthru.commit = pin.commit;
  meta = {
    description = "PipeWire filter that denoises the built-in camera in low light";
    homepage = "https://github.com/aurora-silicon/camera-denoise";
    license = lib.licenses.mit;
    mainProgram = "aurora-camera-denoise";
    platforms = [ "aarch64-linux" ];
  };
}
