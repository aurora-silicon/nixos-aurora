{ stdenvNoCC, lib, fetchurl, python3 }:
let
  # Same aurora-platform source as aurora-firstboot.
  pin = (builtins.fromJSON (builtins.readFile ./sources.json)).aurora-firstboot;
in stdenvNoCC.mkDerivation {
  pname = "aurora-power-budget";
  inherit (pin) version;
  src = fetchurl { name = "aurora-firstboot-${pin.commit}.tar.gz"; url = pin.source_url; hash = pin.nix_hash; };
  buildInputs = [ python3 ];
  dontBuild = true;
  installPhase = ''
    runHook preInstall
    make install-power PREFIX=$out
    # NixOS declares the unit in modules/power-budget.nix.
    rm -r $out/lib/systemd
    patchShebangs $out/libexec/aurora
    runHook postInstall
  '';
  meta.license = lib.licenses.mit;
}
