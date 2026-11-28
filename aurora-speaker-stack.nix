{ lib, stdenvNoCC, makeWrapper, python3, alsa-utils, systemd }:
stdenvNoCC.mkDerivation {
  pname = "aurora-speaker-stack";
  version = "0.1";
  src = ./speaker-stack;
  nativeBuildInputs = [ makeWrapper python3 ];
  dontBuild = true;
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    ${python3}/bin/python3 -I aurora-speaker-stack --help >/dev/null
    runHook postCheck
  '';
  installPhase = ''
    runHook preInstall
    install -Dm755 aurora-speaker-stack $out/bin/aurora-speaker-stack
    install -Dm644 aurora-speaker-stack.8 $out/share/man/man8/aurora-speaker-stack.8
    install -Dm644 README.md $out/share/doc/aurora-audio/README.md
    substituteInPlace $out/bin/aurora-speaker-stack \
      --replace-fail '#!/usr/bin/python3 -I' '#!${python3}/bin/python3 -I'
    wrapProgram $out/bin/aurora-speaker-stack \
      --prefix PATH : ${lib.makeBinPath [ alsa-utils systemd ]}
    runHook postInstall
  '';
  meta = {
    description = "Select the Apple Silicon speaker protection stack (sgv2 default, speakersafetyd user opt-out)";
    license = lib.licenses.mit;
    platforms = [ "aarch64-linux" ];
    mainProgram = "aurora-speaker-stack";
  };
}
