{ stdenvNoCC, lib, fetchurl, makeWrapper, python3, systemdUkify, sbsigntool, openssl, coreutils, util-linux }:
let
  pin = (builtins.fromJSON (builtins.readFile ./sources.json)).aurora-secboot;
  stub = "${systemdUkify}/lib/systemd/boot/efi/linuxaa64.efi.stub";
in stdenvNoCC.mkDerivation {
  pname = "aurora-secboot";
  inherit (pin) version;
  src = fetchurl { name = "aurora-secboot-${pin.commit}.tar.gz"; url = pin.source_url; hash = pin.nix_hash; };
  nativeBuildInputs = [ makeWrapper ];
  buildInputs = [ python3 ];
  dontBuild = true;
  installPhase = ''
    runHook preInstall
    install -Dm755 secboot/aurora-secboot $out/bin/aurora-secboot
    patchShebangs $out/bin
    # ukify, sbsign/sbverify and openssl from the store; the systemd stub is
    # not under /usr/lib on NixOS.
    wrapProgram $out/bin/aurora-secboot \
      --prefix PATH : ${lib.makeBinPath [ systemdUkify sbsigntool openssl coreutils util-linux ]} \
      --set-default AURORA_SECBOOT_STUB ${stub}
    runHook postInstall
  '';
  passthru = { inherit stub; inherit (pin) commit; };
  meta = {
    description = "Build, sign and install signed UKIs for the Aurora secure boot path";
    homepage = "https://github.com/aurora-silicon/aurora-platform";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "aurora-secboot";
  };
}
