{ lib, stdenvNoCC, symlinkJoin, alsa-ucm-conf, src, pin }:
let
  models = stdenvNoCC.mkDerivation {
    pname = "aurora-ucm-models";
    inherit (pin) version;
    inherit src;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      mkdir -p "$out/share/alsa"
      cp -r ucm2 "$out/share/alsa/"
      echo ${pin.commit} > "$out/.aurora-ucm-commit"
      runHook postInstall
    '';
  };
in symlinkJoin {
  pname = "alsa-ucm-conf-aurora";
  inherit (models) version src;
  paths = [ models alsa-ucm-conf ];
  postBuild = ''
    test "$(cat "$out/.aurora-ucm-commit")" = ${pin.commit}
    grep -qF 'JackControl "Internal Mic Jack"' \
      "$out/share/alsa/ucm2/conf.d/aop_audio/3chan/HiFi.conf"
    test -f "$out/share/alsa/ucm2/conf.d/macaudio/MacBook Neo J700.conf"
  '';
  passthru.commit = pin.commit;
  meta = {
    description = "Aurora model profiles with native common ALSA UCM definitions";
    homepage = "https://github.com/aurora-silicon/alsa-ucm-conf-asahi";
    license = lib.licenses.bsd3;
    platforms = [ "aarch64-linux" ];
  };
}
