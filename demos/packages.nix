{ pkgs }:
let
  inherit (pkgs) lib;
  pins = builtins.fromJSON (builtins.readFile ./sources.json);
  source = name: if pins.${name} ? local_archive then
    let path = ./. + "/${pins.${name}.local_archive}";
    in assert builtins.hashFile "sha256" path == pins.${name}.sha256; path
    else pkgs.fetchurl {
    url = pins.${name}.source_url;
    sha256 = pins.${name}.sha256;
    name = "${name}-${pins.${name}.commit}.tar.gz";
  };
  libane = pkgs.stdenv.mkDerivation {
    pname = "aurora-demo-libane";
    version = pins.libane.version;
    src = source "libane";
    buildInputs = [ pkgs.libdrm ];
    env.NIX_CFLAGS_COMPILE = "-I${lib.getDev pkgs.libdrm}/include/libdrm";
    makeFlags = [ "-C" "libane" "CFLAGS=-O2 -fPIC" ];
    installPhase = ''
      mkdir -p $out/lib $out/include/libane $out/share/licenses/libane
      cp libane/libane.a $out/lib/
      cp libane/*.h $out/include/libane/
      cp LICENSE $out/share/licenses/libane/
    '';
    meta.license = lib.licenses.mit;
  };
  models = pkgs.stdenvNoCC.mkDerivation {
    pname = "aurora-models";
    version = "0.1.0";
    src = ./.;
    dontBuild = true;
    nativeBuildInputs = [ pkgs.makeWrapper ];
    installPhase = ''
      mkdir -p $out/bin $out/share/aurora-models $out/share/licenses/aurora-models
      cp models.json export_rnnoise.py $out/share/aurora-models/
      cp LICENSE capture-ns-LICENSE $out/share/licenses/aurora-models/
      substitute aurora-model-fetch $out/bin/aurora-model-fetch \
        --replace-fail '@DATA@' "$out/share/aurora-models"
      chmod +x $out/bin/aurora-model-fetch
      patchShebangs $out/bin
      wrapProgram $out/bin/aurora-model-fetch --set-default SSL_CERT_FILE '${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt'
    '';
    meta = { license = lib.licenses.mit; mainProgram = "aurora-model-fetch"; };
  };
  rnnoise = pkgs.stdenv.mkDerivation {
    pname = "aurora-rnnoise";
    version = pins.rnnoise.version;
    src = source "rnnoise";
    nativeBuildInputs = [ pkgs.autoreconfHook pkgs.pkg-config ];
    configureFlags = [ "--disable-examples" ];
    doCheck = true;
    postInstall = ''
      install -Dm644 COPYING $out/share/licenses/aurora-rnnoise/COPYING
    '';
    meta = { license = lib.licenses.bsd3; platforms = [ "aarch64-linux" ]; };
  };
  libdf = pkgs.rustPlatform.buildRustPackage {
    pname = "aurora-libdf";
    version = pins.libdf.version;
    src = source "libdf";
    # HDF5 belongs to the unused dataset feature. Import the same lock without
    # fetching that repository's large C-library submodule for the C API build.
    cargoDeps = (pkgs.callPackage
      (pkgs.path + "/pkgs/build-support/rust/import-cargo-lock.nix") {
        fetchgit = args: pkgs.fetchgit (args // { fetchSubmodules = false; });
      }) {
        lockFile = ./df-Cargo.lock;
        outputHashes."hdf5-0.8.1" = "sha256-arJceSimhb9TTv7uBMIbOmRhjy09R4786sxQXvQfpAA=";
      };
    postPatch = ''
      cp ${./df-Cargo.lock} Cargo.lock
      substituteInPlace libDF/Cargo.toml \
        --replace-fail 'capi = ["tract", "default-model", "dep:ndarray", "logging"]' 'capi = ["tract", "dep:ndarray", "logging"]'
    '';
    env.CARGO_PROFILE_RELEASE_OPT_LEVEL = "2";
    env.CARGO_PROFILE_RELEASE_LTO = "false";
    buildAndTestSubdir = "libDF";
    buildNoDefaultFeatures = true;
    buildFeatures = [ "capi" ];
    # The capture derivation below tests the C API on synthetic buffers using
    # the audited external model; Rust's workspace tests require other features.
    doCheck = false;
    installPhase = ''
      mkdir -p $out/lib $out/share/licenses/aurora-libdf
      cp target/${pkgs.stdenv.hostPlatform.rust.rustcTarget}/release/libdf.so $out/lib/
      cp LICENSE-MIT LICENSE-APACHE $out/share/licenses/aurora-libdf/
    '';
    meta = { license = [ lib.licenses.mit lib.licenses.asl20 ]; platforms = [ "aarch64-linux" ]; };
  };
  capture = pkgs.stdenv.mkDerivation {
    pname = "aurora-capture-ns";
    version = pins.aurora-capture-ns.version;
    src = source "aurora-capture-ns";
    nativeBuildInputs = [ pkgs.python3 pkgs.makeWrapper ];
    buildInputs = [ pkgs.openssl pkgs.ladspaH ];
    makeFlags = [ "LIBANE_DIR=${libane}/include/libane" "LIBANE_LIB=${libane}/lib/libane.a" ];
    doCheck = true;
    checkPhase = ''
      export AURORA_RNNOISE_LIBRARY=${rnnoise}/lib/librnnoise.so
      export AURORA_RNNOISE_MODEL=$TMPDIR/rnnoise-v011.txt
      mkdir rnnoise-source df-source
      tar -xzf ${source "rnnoise"} --strip-components=1 -C rnnoise-source
      tar -xzf ${source "libdf"} --strip-components=1 -C df-source
      python3 tools/export_rnnoise.py rnnoise-source/src/rnn_data.c "$AURORA_RNNOISE_MODEL"
      export AURORA_DF_LIBRARY=${libdf}/lib/libdf.so
      export AURORA_DF_MODEL=$PWD/df-source/models/DeepFilterNet3_onnx.tar.gz
      make "''${makeFlags[@]}" build/test-stream build/test-engine build/test-ladspa
      build/test-stream
      build/test-engine
      build/test-ladspa build/libaurora_capture_ns.so
      python3 -m unittest discover -s tests -p test_config.py -v
    '';
    installPhase = ''
      mkdir -p $out/bin $out/lib/ladspa $out/libexec/aurora-capture-ns $out/share/licenses/aurora-capture-ns
      cp build/libaurora_capture_ns.so $out/lib/ladspa/
      cp tools/aurora-capture-ns $out/libexec/aurora-capture-ns/launcher.py
      cp LICENSE $out/share/licenses/aurora-capture-ns/
      cp ${libane}/share/licenses/libane/LICENSE $out/share/licenses/aurora-capture-ns/libane-LICENSE
      substitute ${./aurora-capture-ns} $out/bin/aurora-capture-ns \
        --replace-fail '@FETCH@' '${models}/bin/aurora-model-fetch' \
        --replace-fail '@RNNOISE@' '${rnnoise}/lib/librnnoise.so.0' \
        --replace-fail '@LIBDF@' '${libdf}/lib/libdf.so' \
        --replace-fail '@LAUNCHER@' "$out/libexec/aurora-capture-ns/launcher.py" \
        --replace-fail '@PLUGIN@' "$out/lib/ladspa/libaurora_capture_ns.so"
      chmod +x $out/bin/aurora-capture-ns
      substituteInPlace $out/libexec/aurora-capture-ns/launcher.py --replace-fail '["pw-dump"]' '["${pkgs.pipewire}/bin/pw-dump"]' --replace-fail '["pipewire",' '["${pkgs.pipewire}/bin/pipewire",'
      patchShebangs $out/bin $out/libexec
    '';
    meta = { license = lib.licenses.mit; platforms = [ "aarch64-linux" ]; mainProgram = "aurora-capture-ns"; };
  };
  whisper = pkgs.stdenv.mkDerivation {
    pname = "whisper-cpp-aurora";
    version = pins."whisper.cpp-aurora".version;
    src = source "whisper.cpp-aurora";
    nativeBuildInputs = [ pkgs.cmake pkgs.ninja pkgs.shaderc pkgs.python3 pkgs.makeWrapper ];
    buildInputs = [ pkgs.vulkan-headers pkgs.vulkan-loader ];
    cmakeFlags = [
      "-DBUILD_SHARED_LIBS=OFF" "-DGGML_NATIVE=OFF" "-DGGML_VULKAN=ON"
      "-DWHISPER_ANE=ON" "-DWHISPER_SDL2=OFF" "-DWHISPER_COREML=OFF"
      "-DWHISPER_BUILD_SERVER=OFF" "-DWHISPER_BUILD_TESTS=ON"
      "-DLIBANE_INCLUDE_DIR=${libane}/include/libane" "-DLIBANE_LIBRARY=${libane}/lib/libane.a"
      "-DWHISPER_ANE_WORKER_PATH=${placeholder "out"}/share/whisper-aurora/ane/worker.py"
    ];
    doCheck = true;
    checkPhase = ''
      ctest -L unit --output-on-failure
      python3 ../tests/ane/test_worker.py
    '';
    installPhase = ''
      mkdir -p $out/bin $out/share/whisper-aurora/ane $out/share/licenses/whisper-cpp-aurora
      cp bin/whisper-cli $out/bin/whisper-cli-aurora
      cp bin/whisper-bench $out/bin/whisper-bench-aurora
      cp ../models/ane/worker.py $out/share/whisper-aurora/ane/
      cp ../LICENSE $out/share/licenses/whisper-cpp-aurora/
      cp ${libane}/share/licenses/libane/LICENSE $out/share/licenses/whisper-cpp-aurora/libane-LICENSE
      substitute ${./whisper.cpp-aurora} $out/bin/whisper.cpp-aurora \
        --replace-fail '@CLI@' "$out/bin/whisper-cli-aurora" \
        --replace-fail '@FETCH@' '${models}/bin/aurora-model-fetch' \
        --replace-fail '@VULKANINFO@' '${pkgs.vulkan-tools}/bin/vulkaninfo'
      chmod +x $out/bin/whisper.cpp-aurora
      patchShebangs $out/bin
      wrapProgram $out/bin/whisper.cpp-aurora --set WHISPER_ANE_PYTHON '${pkgs.python3.withPackages (p: [ p.numpy ])}/bin/python3'
    '';
    meta = { license = lib.licenses.mit; platforms = [ "aarch64-linux" ]; mainProgram = "whisper.cpp-aurora"; };
  };
in { inherit models rnnoise libdf capture whisper; }
