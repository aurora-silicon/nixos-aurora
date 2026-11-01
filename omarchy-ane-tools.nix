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
  postPatch = ''
    python3 ${./ane/fix-smoke.py}
    # The offline suite copies this shell helper and creates a Python wrapper.
    # Both execute inside the sandbox, where /usr/bin/env is absent.
    patchShebangs packaging/omarchy-ane-check
    substituteInPlace tools/test_ane_firmware_fetch.py \
      --replace-fail '#!/usr/bin/env python3' '#!${python3}/bin/python3'
  '';
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
    python3 ${./ane/nixos-firmware.py}
    install -Dm755 tools/ane-run "$out/bin/omarchy-ane-run"
    install -Dm755 -t "$out/bin" packaging/omarchy-ane-smoke packaging/omarchy-ane-firmware-fetch
    for gen in h13 h14; do
      install -Dm644 "fixtures/$gen-anec/add/program-0.anec" \
        "$out/share/omarchy-ane/fixtures/$gen-anec/add/program-0.anec"
    done
    install -Dm644 LICENSE "$out/share/licenses/omarchy-ane-tools/LICENSE"
    install -Dm644 ${./ane/70-omarchy-ane.rules} "$out/lib/udev/rules.d/70-omarchy-ane.rules"
    install -Dm644 ${./ane/omarchy-ane-tools.sysusers} "$out/lib/sysusers.d/omarchy-ane-tools.conf"
    python3 ${./ane/test-firmware.py} "$out/bin/omarchy-ane-firmware-fetch"
    test ! -d "$out/bin/__pycache__"
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
