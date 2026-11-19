{ lib, stdenvNoCC, python3, makeWrapper, alsa-utils, glib, vulkan-tools, mesa-demos, iw
, smartmontools, bluez, libglvnd, src, pin }:
let
  # Textual draws the dashboard; everything else is the standard library.
  py = python3.withPackages (ps: [ ps.textual ]);
in
stdenvNoCC.mkDerivation {
  pname = "aurora-diag";
  inherit (pin) version;
  inherit src;
  nativeBuildInputs = [ makeWrapper py ];
  postPatch = ''
    for f in bin/aurora-diag bin/aurora-panic-log; do
      substituteInPlace $f --replace-fail "#!/usr/bin/python3 -I" "#!${py.interpreter} -I"
    done
  '';
  dontBuild = true;
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    make check PYTHON=${py.interpreter}
    runHook postCheck
  '';
  installPhase = ''
    runHook preInstall
    make install DESTDIR=$out PREFIX=
    install -Dm644 LICENSE $out/share/licenses/aurora-diag/LICENSE
    # The tools it reads are optional, as on Fedora and ALARM; the system's
    # own copies come first. EGL is loaded with ctypes.
    wrapProgram $out/bin/aurora-diag \
      --suffix PATH : ${lib.makeBinPath [ alsa-utils glib vulkan-tools mesa-demos iw smartmontools bluez ]} \
      --prefix LD_LIBRARY_PATH : /run/opengl-driver/lib:${lib.makeLibraryPath [ libglvnd ]}
    runHook postInstall
  '';
  doInstallCheck = true;
  installCheckPhase = ''
    runHook preInstallCheck
    mkdir -p "$TMPDIR/empty-root"
    AURORA_DIAG_ROOT="$TMPDIR/empty-root" $out/bin/aurora-diag ane --json > ane.json
    ${py.interpreter} -c 'import json; d = json.load(open("ane.json")); assert d["devices"] == [] and d["dt_nodes"] == []; assert d["checks"][0]["level"] == "warn"'
    $out/bin/aurora-panic-log --help > /dev/null
    runHook postInstallCheck
  '';
  passthru.commit = pin.commit;
  meta = {
    description = "Bring-up diagnostics and regression checks for Apple silicon Macs (development only)";
    homepage = "https://github.com/aurora-silicon/aurora-diag";
    license = lib.licenses.mit;
    mainProgram = "aurora-diag";
    platforms = lib.platforms.linux;
  };
}
