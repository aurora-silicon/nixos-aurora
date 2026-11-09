{ lib, stdenvNoCC, makeWrapper, python3, lzfse, util-linux, alsa-utils, systemd, gnumake, speakerguardd-v2, src, version }:
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
    # v2's helpers live in its store path, not /usr/libexec: point the tool there
    # (without it the tool reports v2 as not installed and never switches).
    substituteInPlace $out/lib/aurora-speaker-upgrade/aurora_speaker_upgrade/upgrade.py \
      --replace-fail 'LIBEXEC = ("/usr/libexec/speakerguardd-v2",' 'LIBEXEC = ("${speakerguardd-v2}/libexec/speakerguardd-v2", "/usr/libexec/speakerguardd-v2",' \
      --replace-fail 'PARITY = ("/usr/share/speakerguardd/parity.json",)' 'PARITY = ("${speakerguardd-v2}/share/speakerguardd/parity.json", "/usr/share/speakerguardd/parity.json")'
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
