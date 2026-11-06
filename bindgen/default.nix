{ lib, rustPlatform, fetchurl, pkg-config, llvmPackages, makeWrapper, python3, rustc, rustfmt }:
let
  manifest = builtins.fromJSON (builtins.readFile ./sources.json);
  # Nix recipe edits must not become inputs to the compiler's fixture tests.
  testSource = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [ ./test.py ./tests ];
  };
in rustPlatform.buildRustPackage {
  pname = "aurora-bindgen";
  inherit (manifest) version;
  src = fetchurl {
    name = "rust-bindgen-${manifest.version}.tar.gz";
    url = manifest.source_url;
    sha256 = manifest.source_sha256;
  };
  cargoLock.lockFile = ../locks/bindgen.Cargo.lock;
  patches = map (name: ./patches + ("/" + name)) (builtins.attrNames manifest.patches);
  nativeBuildInputs = [ pkg-config makeWrapper python3 rustfmt llvmPackages.clang ];
  buildInputs = [ llvmPackages.libclang ];
  cargoBuildFlags = [ "-p" "bindgen-cli" ];
  LIBCLANG_PATH = "${lib.getLib llvmPackages.libclang}/lib";
  RUSTFMT = "${rustfmt}/bin/rustfmt";
  checkPhase = ''
    runHook preCheck
    python3 ${testSource}/test.py --bindgen target/aarch64-unknown-linux-gnu/release/bindgen \
      --rustc ${rustc}/bin/rustc --clang ${llvmPackages.clang}/bin/clang \
      --output-dir "$TMPDIR/bindgen-layout-checks"
    runHook postCheck
  '';
  postInstall = ''
    wrapProgram "$out/bin/bindgen" --set LIBCLANG_PATH "$LIBCLANG_PATH" --set RUSTFMT "$RUSTFMT"
  '';
}
