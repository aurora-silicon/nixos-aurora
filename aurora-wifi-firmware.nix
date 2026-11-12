{ lib, stdenvNoCC, makeWrapper, python3, lzfse, util-linux, systemd, gnumake, src, version }:
stdenvNoCC.mkDerivation {
  pname = "aurora-wifi-firmware";
  inherit src version;
  nativeBuildInputs = [ gnumake makeWrapper python3 ];
  dontBuild = true;
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    ${python3}/bin/python3 -I -m unittest discover -s tests -p 'test_wifi_firmware_*.py'
    runHook postCheck
  '';
  installPhase = ''
    runHook preInstall
    make -C tools/wifi-firmware install DESTDIR= PREFIX=$out UNITDIR=$out/lib/systemd/system \
      PYTHON=${python3}/bin/python3
    wrapProgram $out/bin/aurora-wifi-firmware \
      --set-default AURORA_LZFSE_LIB ${lzfse}/lib/liblzfse.so \
      --prefix PATH : ${lib.makeBinPath [ util-linux systemd ]}
    runHook postInstall
  '';
  meta = {
    description = "Keep the Wi-Fi firmware on the installed macOS's (read from the macOS system volume, applied at the next boot)";
    license = lib.licenses.mit;
    platforms = [ "aarch64-linux" ];
    mainProgram = "aurora-wifi-firmware";
  };
}
