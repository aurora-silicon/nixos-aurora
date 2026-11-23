{ pkgs, nixpkgs, system, overlays }:
let
  firmware = pkgs.runCommand "ane-test-firmware" { } ''
    mkdir -p "$out/lib/firmware/apple/ane"
    echo 'synthetic packaging test marker; no firmware' > "$out/lib/firmware/apple/ane/test-marker"
  '';
  probe = nixpkgs.lib.nixosSystem {
    inherit system;
    modules = [ ../modules/ane.nix {
      nixpkgs.overlays = overlays;
      system.stateVersion = "26.05";
      aurora.ane.enable = true;
      aurora.ane.firmwarePackage = firmware;
    } ];
  };
  cfg = probe.config;
in assert builtins.elem probe.pkgs.mil-hwx-compiler cfg.environment.systemPackages;
   pkgs.runCommand "ane-firmware-and-udev-check" { } ''
     test -f ${cfg.hardware.firmware}/lib/firmware/apple/ane/test-marker
     test ! -f ${cfg.hardware.firmware}/lib/firmware/apple/ane/test-marker.zst
     # The /dev/accel policy is the platform module's (checks/fedora-parity.nix).
     test ! -e ${pkgs.omarchy-ane-tools}/lib/udev
     test ! -e ${pkgs.omarchy-ane-tools}/lib/sysusers.d
     touch $out
   ''
