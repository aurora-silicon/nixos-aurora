# Overlay entry for nixos-aurora (overlay.nix), next to the other pinned
# packages. Opt-in: add pkgs.aurora-diag to environment.systemPackages.
{ stdenvNoCC, python3, makeWrapper, alsa-utils, glib, vulkan-tools, mesa-demos, libglvnd, lib, src, version }:
let
  py = python3.withPackages (ps: [ ps.textual ]);
in
stdenvNoCC.mkDerivation {
  pname = "aurora-diag";
  inherit version src;
  nativeBuildInputs = [ makeWrapper py ];
  buildInputs = [ py ];
  dontBuild = true;
  doCheck = true;
  checkPhase = "make check PYTHON=${py.interpreter}";
  installPhase = ''
    make install DESTDIR=$out PREFIX=
    substituteInPlace $out/bin/aurora-diag --replace-fail "#!/usr/bin/python3 -I" "#!${py.interpreter} -I"
    wrapProgram $out/bin/aurora-diag \
      --prefix PATH : ${lib.makeBinPath [ alsa-utils glib vulkan-tools mesa-demos ]} \
      --prefix LD_LIBRARY_PATH : /run/opengl-driver/lib:${lib.makeLibraryPath [ libglvnd ]}
  '';
  doInstallCheck = true;
  installCheckPhase = ''
    mkdir -p "$TMPDIR/ane-empty-root"
    AURORA_DIAG_ROOT="$TMPDIR/ane-empty-root" $out/bin/aurora-diag ane --json > ane-installed.json
    ${py.interpreter} -c 'import json; d=json.load(open("ane-installed.json")); assert d["devices"] == [] and d["dt_nodes"] == []; assert d["checks"][0]["level"] == "warn"'
  '';
  meta = {
    description = "Bring-up diagnostics and regression checks for Apple silicon Macs (development only)";
    license = lib.licenses.mit;
    mainProgram = "aurora-diag";
  };
}
