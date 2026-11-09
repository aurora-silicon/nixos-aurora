# Adapted from the user-maintained m4rch GE-Proton package; see README.md.
{
  lib,
  stdenvNoCC,
  fetchurl,
  callPackage,
  llvmPackages,
  binutils,
}:
let
  pin = builtins.fromJSON (builtins.readFile ./sources.json);
  patchedNtdll = callPackage ./ntdll.nix { inherit (llvmPackages) clang-unwrapped lld llvm; };
in
stdenvNoCC.mkDerivation {
  pname = "aurora-proton";
  inherit (pin) version;
  src = fetchurl pin.archives.proton;
  nativeBuildInputs = [ binutils ];
  dontBuild = true;
  dontFixup = true;
  installPhase = ''
    runHook preInstall
    original=files/lib/wine/aarch64-unix/ntdll.so
    test -f "$original"
    # Refuse to combine Wine builds with different exported interfaces.
    nm -D --defined-only --format=posix "$original" | awk '{print $1}' | sort > original-symbols
    nm -D --defined-only --format=posix ${patchedNtdll}/lib/ntdll.so | awk '{print $1}' | sort > patched-symbols
    diff -u original-symbols patched-symbols
    mkdir -p "$out"
    cp -a . "$out/"
    chmod u+w "$out/$original"
    cp ${patchedNtdll}/lib/ntdll.so "$out/$original"
    chmod u+w "$out/compatibilitytool.vdf"
    substituteInPlace "$out/compatibilitytool.vdf" \
      --replace-fail 'GE-Proton${pin.version}-aarch64' 'Aurora-Proton${pin.version}'
    rm "$out/original-symbols" "$out/patched-symbols"
    install -Dm644 ${./wine-sve-guard.patch} "$out/aurora-wine-sve-guard.patch"
    runHook postInstall
  '';
  passthru = { inherit patchedNtdll; };
  meta = {
    description = "Native ARM64 GE-Proton with Aurora SME signal-frame fix";
    platforms = [ "aarch64-linux" ];
    license = [ lib.licenses.bsd3 lib.licenses.lgpl21Plus ];
    homepage = "https://github.com/GloriousEggroll/proton-ge-custom";
  };
}
