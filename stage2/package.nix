{ lib, stdenvNoCC, makeWrapper, python3, dtc, util-linux, coreutils }:
# The Stage 2 trial updater: fedora-aurora's bootchain.py, unchanged, and the
# NixOS adapter around it (modules/installed.nix runs it). The install check
# runs both suites against the installed copies, with dtc.
stdenvNoCC.mkDerivation {
  pname = "aurora-stage2";
  version = "20261108";
  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [
      ./bootchain.py ./nixos_stage2.py ./test_bootchain.py ./test_nixos_stage2.py ./provenance.json
    ];
  };
  nativeBuildInputs = [ makeWrapper ];
  dontConfigure = true;
  dontBuild = true;
  installPhase = ''
    runHook preInstall
    install -Dm644 bootchain.py nixos_stage2.py -t $out/libexec/aurora
    makeWrapper ${python3.interpreter} $out/bin/aurora-stage2 \
      --add-flags "-I $out/libexec/aurora/nixos_stage2.py" \
      --prefix PATH : ${lib.makeBinPath [ dtc util-linux coreutils ]}
    runHook postInstall
  '';
  doInstallCheck = true;
  nativeInstallCheckInputs = [ python3 dtc util-linux coreutils ];
  installCheckPhase = ''
    runHook preInstallCheck
    python3 -I -m py_compile $out/libexec/aurora/bootchain.py $out/libexec/aurora/nixos_stage2.py
    BOOTCHAIN_MODULE=$out/libexec/aurora/bootchain.py python3 -I test_bootchain.py
    NIXOS_STAGE2_MODULE=$out/libexec/aurora/nixos_stage2.py python3 -I test_nixos_stage2.py
    $out/bin/aurora-stage2 --help > /dev/null
    runHook postInstallCheck
  '';
  meta = {
    description = "Trial-then-commit Stage 2 updates for Aurora NixOS";
    license = lib.licenses.mit;
    mainProgram = "aurora-stage2";
    platforms = lib.platforms.linux;
  };
}
