{ stdenvNoCC, lib, makeWrapper, bash, coreutils, keyutils, kmod, python3, util-linux, gnugrep }:
stdenvNoCC.mkDerivation {
  pname = "aurora-sep";
  version = "1.4";
  src = ./.;
  nativeBuildInputs = [ makeWrapper python3 bash ];
  dontBuild = true;
  installPhase = ''
    runHook preInstall
    install -Dm755 load-driver $out/libexec/aurora-sep-load
    install -Dm755 aurora-sep-ready $out/libexec/aurora-sep-ready
    for helper in prepare-sep-calibration extract-mesa-calibration; do
      install -Dm755 "$helper" "$out/libexec/aurora/$helper"
    done
    substituteInPlace $out/libexec/aurora/prepare-sep-calibration \
      --replace-fail /usr/libexec/aurora/extract-mesa-calibration $out/libexec/aurora/extract-mesa-calibration
    patchShebangs $out/libexec
    for helper in $out/libexec/aurora-sep-* $out/libexec/aurora/prepare-sep-calibration; do
      wrapProgram "$helper" --prefix PATH : ${lib.makeBinPath [ bash coreutils keyutils kmod util-linux gnugrep ]}
    done
    install -Dm644 README.md $out/share/doc/aurora-sep/README.md
    install -Dm644 XART-SAFETY.md $out/share/doc/aurora-sep/XART-SAFETY.md
    runHook postInstall
  '';
  meta.license = lib.licenses.gpl2Only;
}
