{ stdenvNoCC, lib }:
let
  sizes = map toString [ 16 22 24 32 48 64 96 128 256 512 ];
in
stdenvNoCC.mkDerivation {
  pname = "aurora-logos";
  version = "1";
  # Packaging edits must not change the artwork source snapshot.
  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions ([ ./LICENSE ./provenance.json ]
      ++ map (size: ./. + "/AuroraLogo-${size}.png") sizes);
  };
  dontBuild = true;
  installPhase = ''
    runHook preInstall
    for size in ${lib.concatStringsSep " " sizes}; do
      install -Dm644 "AuroraLogo-$size.png" \
        "$out/share/icons/hicolor/''${size}x''${size}/apps/aurora-logo-icon.png"
      install -Dm644 "AuroraLogo-$size.png" \
        "$out/share/icons/hicolor/''${size}x''${size}/places/start-here.png"
    done
    install -Dm644 AuroraLogo-256.png "$out/share/pixmaps/system-logo-white.png"
    install -Dm644 LICENSE "$out/share/licenses/aurora-logos/LICENSE"
    install -Dm644 provenance.json "$out/share/doc/aurora-logos/provenance.json"
    runHook postInstall
  '';
  meta = {
    description = "Aurora desktop icons and Plasma distribution artwork";
    homepage = "https://aurorasilicon.org";
    license = lib.licenses.mit;
    platforms = lib.platforms.all;
  };
}
