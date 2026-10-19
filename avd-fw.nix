{ lib, stdenvNoCC, meson, ninja, python3, llvmPackages_22, src, version }:
stdenvNoCC.mkDerivation {
  pname = "aurora-avd-fw";
  inherit src version;
  outputs = [ "out" "debug" ];
  nativeBuildInputs = [ meson ninja python3 llvmPackages_22.clang-unwrapped
    llvmPackages_22.llvm llvmPackages_22.lld ];
  strictDeps = true;
  dontStrip = true;
  configurePhase = ''
    runHook preConfigure
    unset CFLAGS CXXFLAGS CPPFLAGS LDFLAGS
    meson setup --cross-file llvm.ini --prefix="$out" --libdir=lib \
      -Doptimization=2 -Ddebug=false -Dc_link_args=-fuse-ld=lld build
    runHook postConfigure
  '';
  buildPhase = ''
    runHook preBuild
    meson compile -C build
    runHook postBuild
  '';
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    python3 ${./firmware/check-avd.py} build
    runHook postCheck
  '';
  installPhase = ''
    runHook preInstall
    mkdir -p "$out/lib/firmware/apple" "$debug/lib/debug/firmware/apple"
    find build -type f -name 'avd-fw-*.bin' \
      -exec install -m644 -t "$out/lib/firmware/apple" {} +
    install -m644 build/avd-fw-*.elf "$debug/lib/debug/firmware/apple/"
    install -Dm644 LICENSE "$out/share/licenses/aurora-avd-fw/LICENSE"
    runHook postInstall
  '';
  meta = {
    description = "Open Aurora firmware for Apple Video Decoder v2 through v5";
    homepage = "https://github.com/aurora-silicon/avd-fw";
    license = lib.licenses.mit;
    platforms = [ "aarch64-linux" ];
  };
}
