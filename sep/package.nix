{ stdenvNoCC, lib, makeWrapper, bash, coreutils, keyutils, kmod, python3, util-linux, gnugrep }:
stdenvNoCC.mkDerivation {
  pname = "aurora-sep";
  version = "1.8";
  src = ./.;
  nativeBuildInputs = [ makeWrapper python3 bash ];
  dontBuild = true;
  installPhase = ''
    runHook preInstall
    install -Dm755 load-driver $out/libexec/aurora-sep-load
    install -Dm755 aurora-sep-ready $out/libexec/aurora-sep-ready
    install -Dm755 aurora-sep-greeter-fingerprint $out/libexec/aurora-sep-greeter-fingerprint
    # GNOME Shell lives in the store; the module names it.
    substituteInPlace $out/libexec/aurora-sep-greeter-fingerprint \
      --replace-fail 'for f in /usr/lib64/gnome-shell/libshell-*.so' \
        'for f in "''${AURORA_SEP_GNOME_SHELL:-/nonexistent}"/lib/gnome-shell/libshell-*.so /usr/lib64/gnome-shell/libshell-*.so'
    for helper in prepare-sep-calibration extract-mesa-calibration sensor-present; do
      install -Dm755 "$helper" "$out/libexec/aurora/$helper"
    done
    substituteInPlace $out/libexec/aurora/prepare-sep-calibration \
      --replace-fail /usr/libexec/aurora/extract-mesa-calibration $out/libexec/aurora/extract-mesa-calibration
    patchShebangs $out/libexec
    for helper in $out/libexec/aurora-sep-load $out/libexec/aurora-sep-ready $out/libexec/aurora/prepare-sep-calibration $out/libexec/aurora/sensor-present; do
      wrapProgram "$helper" --prefix PATH : ${lib.makeBinPath [ bash coreutils keyutils kmod util-linux gnugrep ]}
    done
    for doc in README.md XART-SAFETY.md OS-IDENTITY.md logind-aurora-sep.conf; do
      install -Dm644 "$doc" "$out/share/doc/aurora-sep/$doc"
    done
    runHook postInstall
  '';
  meta.license = lib.licenses.gpl2Only;
}
