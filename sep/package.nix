{ stdenvNoCC, lib, makeWrapper, bash, coreutils, keyutils, kmod, python3, util-linux, gnugrep, systemd }:
stdenvNoCC.mkDerivation {
  pname = "aurora-sep";
  version = "1.17";
  # The libfprint patches and their tests belong to separate derivations.
  # Changing them must not rebuild the unchanged SEP runtime helpers.
  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [
      ./load-driver ./aurora-sep-ready ./aurora-sep-greeter-fingerprint
      ./extract-mesa-calibration ./sensor-present ./touchid-setup-needed
      ./touchid-publish ./aurora-touchid-setup ./aurora-sep
      ./README.md ./XART-SAFETY.md ./OS-IDENTITY.md ./logind-aurora-sep.conf
    ];
  };
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
    for helper in extract-mesa-calibration sensor-present touchid-setup-needed touchid-publish; do
      install -Dm755 "$helper" "$out/libexec/aurora/$helper"
    done
    install -Dm755 aurora-sep $out/bin/aurora-sep
    install -Dm755 aurora-touchid-setup $out/bin/aurora-touchid-setup
    substituteInPlace $out/bin/aurora-touchid-setup \
      --replace-fail /usr/libexec/aurora/extract-mesa-calibration $out/libexec/aurora/extract-mesa-calibration
    patchShebangs $out/libexec $out/bin
    for helper in $out/libexec/aurora-sep-load $out/libexec/aurora-sep-ready $out/libexec/aurora/sensor-present $out/libexec/aurora/touchid-setup-needed $out/libexec/aurora/touchid-publish; do
      wrapProgram "$helper" --prefix PATH : ${lib.makeBinPath [ bash coreutils keyutils kmod util-linux gnugrep systemd ]}
    done
    # aurora-sep status asks systemctl and the journal.
    wrapProgram $out/bin/aurora-sep --prefix PATH : ${lib.makeBinPath [ systemd ]}
    # The kernel's firmware path is on /run here, so the files are kept in
    # /var/lib and linked into it (touchid-publish, and the tool itself).
    wrapProgram $out/bin/aurora-touchid-setup \
      --prefix PATH : ${lib.makeBinPath [ coreutils util-linux ]} \
      --set-default AURORA_TOUCHID_FIRMWARE_DIR /var/lib/aurora-sep/firmware
    for doc in README.md XART-SAFETY.md OS-IDENTITY.md logind-aurora-sep.conf; do
      install -Dm644 "$doc" "$out/share/doc/aurora-sep/$doc"
    done
    runHook postInstall
  '';
  # Not a Mac with a SEP driver: aurora-sep status says so with exit 2.
  doInstallCheck = true;
  installCheckPhase = ''
    runHook preInstallCheck
    status=0
    AURORA_SEP_SYSFS=$TMPDIR/no-sysfs AURORA_SEP_ROOT=$TMPDIR/no-root AURORA_SEP_NO_SYSTEM=1 \
      $out/bin/aurora-sep status || status=$?
    [ "$status" = 2 ]
    runHook postInstallCheck
  '';
  meta.license = lib.licenses.gpl2Only;
}
