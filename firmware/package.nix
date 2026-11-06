{ pkgs }:
let
  admission = pkgs.runCommand "aurora-peripheral-admission" { } ''
    install -Dm755 ${./aurora-peripheral-firmware.sh} $out/bin/aurora-peripheral-admission
    patchShebangs $out/bin/aurora-peripheral-admission
  '';
  firmwareTools = [ pkgs.coreutils pkgs.util-linux pkgs.cpio pkgs.kmod pkgs.gnugrep pkgs.bash pkgs.systemd ];
  extractFirmware = pkgs.writeShellApplication {
    name = "aurora-extract-vendor-firmware";
    runtimeInputs = firmwareTools;
    text = builtins.readFile ./extract-vendor-firmware.sh;
  };
  loadFirmware = pkgs.writeShellApplication {
    name = "aurora-load-vendor-firmware";
    runtimeInputs = [ extractFirmware admission ] ++ firmwareTools;
    text = builtins.readFile ./load-vendor-firmware.sh;
  };
in { inherit admission extractFirmware loadFirmware firmwareTools; }
