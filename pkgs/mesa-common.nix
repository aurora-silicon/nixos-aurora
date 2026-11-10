# Source, compiler and dependency settings shared by the explicit Mesa outputs.
{ lib, mesa, src, version, llvmPackages, spirv-tools, stdenv
, mesa-libclc, spirv-llvm-translator, lm_sensors, libunwind
, rustc, rust-bindgen, rust-cbindgen, valgrind-light, writeText
, commit, guest ? false }:
(mesa.override { stdenv = if guest then stdenv else llvmPackages.stdenv; }).overrideAttrs (old: {
  inherit src version;
  passthru = (old.passthru or { }) // { auroraCommit = commit; };
  env = (old.env or { }) // { MESA_GIT_SHA1_OVERRIDE = commit; }
    // lib.optionalAttrs guest {
      NIX_CFLAGS_COMPILE = "-ffile-prefix-map=/nix/store=/usr/src/nix -ffile-prefix-map=/build=/usr/src/mesa";
    };
  patches = lib.optionals guest [ (writeText "mesa-hk-tests-bind-size-t.patch"
    (builtins.readFile ../patches/mesa-hk-tests-bind-size-t.patch)) ];
  outputs = [ "out" ];
  # Guest debug outputs would retain host source paths. Preserve the build
  # IDs the drivers need explicitly, while shipping stripped guest libraries.
  separateDebugInfo = if guest then false else old.separateDebugInfo;
  mesonAutoFeatures = "auto";
  # Nix splits Clang's library output from LLVM's library directory.
  postPatch = (old.postPatch or "") + lib.optionalString (!guest) ''
    substituteInPlace meson.build --replace-fail 'dirs : llvm_libdir' \
      "dirs : [llvm_libdir, '${lib.getLib llvmPackages.clang-unwrapped}/lib']"
  '';
  preConfigure = lib.optionalString (!guest) (old.preConfigure or "") + ''
    export CC=${if guest then "${stdenv.cc}/bin/cc" else "${llvmPackages.clang}/bin/clang"}
    export CXX=${if guest then "${stdenv.cc}/bin/c++" else "${llvmPackages.clang}/bin/clang++"}
    export CC_FOR_BUILD="$CC"
    export CXX_FOR_BUILD="$CXX"
    "$CC" --version
  '';
  mesonBuildType = "release";
  # The guest builds use the same native x86 shader tools. In particular,
  # they neither build nor link an i686 LLVM/translator stack.
  buildInputs = if guest then lib.filter (input:
    !(lib.elem (lib.getName input) (map lib.getName [ llvmPackages.clang
      llvmPackages.clang-unwrapped llvmPackages.libllvm spirv-tools mesa-libclc
      spirv-llvm-translator lm_sensors libunwind valgrind-light ]))) old.buildInputs else old.buildInputs;
  nativeBuildInputs = if guest then lib.filter (input:
    !(lib.elem (lib.getName input) (map lib.getName [ rustc rust-bindgen rust-cbindgen ])))
    old.nativeBuildInputs else old.nativeBuildInputs;
  mesonFlags = [
    "-Dplatforms=x11,wayland" "-Dgallium-drivers=asahi,zink,softpipe"
    "-Dvulkan-drivers=asahi" "-Dvulkan-layers=" "-Dglvnd=enabled"
    "-Degl=enabled" "-Dgbm=enabled" "-Dglx=dri" "-Dgles1=enabled"
    "-Dgallium-rusticl=false" "-Dgles2=enabled" "-Dvideo-codecs=${if guest then "" else "all"}" "-Dexpat=enabled"
    "-Dzstd=enabled" "-Dlmsensors=${if guest then "disabled" else "enabled"}" "-Dlibunwind=disabled"
    "-Dvalgrind=disabled" "-Db_ndebug=true" "-Dwrap_mode=nodownload"
  ] ++ lib.optionals guest [ "-Dgallium-rusticl=false"
    "-Dc_link_args=-Wl,--build-id=sha1" "-Dcpp_link_args=-Wl,--build-id=sha1" ];
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    meson test --print-errorlogs --num-processes "$NIX_BUILD_CORES"
    runHook postCheck
  '';
  disallowedRequisites = [ ];
  allowedReferences = null;
})
