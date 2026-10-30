{ lib, stdenv, libdrm, python3, src, version }:
stdenv.mkDerivation {
  pname = "omarchy-ane-tools";
  inherit src version;
  strictDeps = true;
  nativeBuildInputs = [ python3 ];
  # libdrm: drm.h for libane, which omarchy-ane-run links statically. The
  # upstream Makefile looks for it under /usr/include/libdrm.
  buildInputs = [ libdrm python3 ];
  env.NIX_CFLAGS_COMPILE = "-I${lib.getDev libdrm}/include/libdrm";
  buildPhase = ''
    runHook preBuild
    make -C libane libane
    make -C tools ane-run
    runHook postBuild
  '';
  # Host-only, no device or network. tools/test_ane_smoke.py is left out: it
  # times fake ANE calls against a 2 s limit and fails on slow (emulated) builders.
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    python3 tools/test_ane_firmware_fetch.py
    runHook postCheck
  '';
  installPhase = ''
    runHook preInstall
    install -Dm755 tools/ane-run "$out/bin/omarchy-ane-run"
    install -Dm755 -t "$out/bin" packaging/omarchy-ane-smoke packaging/omarchy-ane-firmware-fetch
    # omarchy-ane-smoke runs the omarchy-ane-run beside it, and reads its
    # programs from /usr/share/omarchy-ane or from ../fixtures beside itself.
    # Point the second at this package's share directory.
    substituteInPlace "$out/bin/omarchy-ane-smoke" \
      --replace-fail 'HERE.parent / "fixtures"' 'HERE.parent / "share/omarchy-ane/fixtures"'
    for gen in h13 h14; do
      install -Dm644 "fixtures/$gen-anec/add/program-0.anec" \
        "$out/share/omarchy-ane/fixtures/$gen-anec/add/program-0.anec"
    done
    install -Dm644 LICENSE "$out/share/licenses/omarchy-ane-tools/LICENSE"
    runHook postInstall
  '';
  meta = {
    description = "Apple Neural Engine userspace tools for the in-kernel ANE driver";
    homepage = "https://github.com/joshuaswarren/omarchy-ane";
    license = with lib.licenses; [ gpl2Only mit ];
    platforms = [ "aarch64-linux" ];
    mainProgram = "omarchy-ane-smoke";
  };
}
