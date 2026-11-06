{ lib, stdenv, src, pin }:
stdenv.mkDerivation {
  pname = "aurora-userpages";
  inherit (pin) version;
  inherit src;
  # Only the launcher, its prctl header and the license.
  unpackPhase = ''
    runHook preUnpack
    root=${pin.archive_root}
    tar -xzf "$src" "$root/COPYING" "$root/include/uapi/linux/prctl.h" "$root/tools/aurora-userpages"
    sourceRoot=$root
    runHook postUnpack
  '';
  buildPhase = ''
    runHook preBuild
    make -C tools/aurora-userpages
    runHook postBuild
  '';
  installPhase = ''
    runHook preInstall
    install -Dm755 tools/aurora-userpages/userpages "$out/bin/userpages"
    install -Dm644 tools/aurora-userpages/README.rst "$out/share/doc/aurora-userpages/README.rst"
    install -Dm644 COPYING "$out/share/licenses/aurora-userpages/COPYING"
    runHook postInstall
  '';
  doInstallCheck = true;
  installCheckPhase = ''
    "$out/bin/userpages" --help | grep -q '{native|4k|16k|64k} COMMAND'
  '';
  passthru = { inherit (pin) commit; };
  meta = {
    description = "Run programs with 4K userspace pages on the Aurora kernel";
    license = lib.licenses.gpl2Only;
    mainProgram = "userpages";
    platforms = [ "aarch64-linux" ];
  };
}
