{ lib, stdenv, src, pin }:
stdenv.mkDerivation {
  pname = "aurora-kbd-light";
  inherit (pin) version;
  inherit src;
  makeFlags = [ "PREFIX=${placeholder "out"}" "UNITDIR=${placeholder "out"}/lib/systemd/system" ];
  postInstall = ''
    substituteInPlace $out/lib/systemd/system/aurora-kbd-light.service \
      --replace-fail "ExecStart=/usr/bin/aurora-kbd-light" "ExecStart=$out/bin/aurora-kbd-light"
    # The unit's boot start comes before the keyboard backlight LED and the
    # light sensor exist; udev starts it again when either appears (the same
    # rule as alarm-aurora's and fedora-aurora's packages).
    install -Dm644 ${./90-aurora-kbd-light.rules} $out/lib/udev/rules.d/90-aurora-kbd-light.rules
  '';
  passthru.commit = pin.commit;
  meta = {
    description = "Keyboard backlight that follows the ambient light sensor";
    homepage = "https://github.com/aurora-silicon/kbd-light";
    license = lib.licenses.mit;
    mainProgram = "aurora-kbd-light";
    platforms = [ "aarch64-linux" ];
  };
}
