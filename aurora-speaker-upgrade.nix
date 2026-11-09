{ lib, stdenvNoCC, makeWrapper, python3, lzfse, util-linux, alsa-utils, systemd, gnumake, src, version }:
let
  py = python3.withPackages (p: [ p.cryptography ]);
in
stdenvNoCC.mkDerivation {
  pname = "aurora-speaker-upgrade";
  inherit src version;
  nativeBuildInputs = [ gnumake makeWrapper py ];
  dontBuild = true;
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    AURORA_LZFSE_LIB=${lzfse}/lib/liblzfse.so ${py}/bin/python3 -I -m unittest discover -s packaging/upgrade/tests
    runHook postCheck
  '';
  installPhase = ''
    runHook preInstall
    make -C packaging/upgrade install DESTDIR= PREFIX=$out UNITDIR=$out/lib/systemd/system \
      V2UNIT=speakerguardd-v2.service
    substituteInPlace $out/bin/aurora-speaker-upgrade \
      --replace-fail '#!/usr/bin/python3 -I' '#!${py}/bin/python3 -I'
    wrapProgram $out/bin/aurora-speaker-upgrade \
      --set-default AURORA_LZFSE_LIB ${lzfse}/lib/liblzfse.so \
      --prefix PATH : ${lib.makeBinPath [ util-linux alsa-utils systemd ]}
    substituteInPlace $out/lib/systemd/system/aurora-speaker-upgrade.service $out/lib/systemd/system/speakerguardd-v2.service.d/50-aurora-speaker-upgrade.conf \
      --replace-fail /usr/bin/aurora-speaker-upgrade $out/bin/aurora-speaker-upgrade
    runHook postInstall
  '';
  meta = {
    description = "Move the speakers to speakerguardd v2 with this Mac's own tuning (preview, ships disabled)";
    license = lib.licenses.mit;
    platforms = [ "aarch64-linux" ];
    mainProgram = "aurora-speaker-upgrade";
  };
}
