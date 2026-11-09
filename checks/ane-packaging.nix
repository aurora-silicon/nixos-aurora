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
in assert cfg.users.groups ? accel;
   assert builtins.elem probe.pkgs.omarchy-ane-tools cfg.services.udev.packages;
   assert builtins.elem probe.pkgs.mil-hwx-compiler cfg.environment.systemPackages;
   pkgs.runCommand "ane-firmware-and-udev-check" { } ''
     test -f ${cfg.hardware.firmware}/lib/firmware/apple/ane/test-marker
     test ! -f ${cfg.hardware.firmware}/lib/firmware/apple/ane/test-marker.zst
     grep -F 'GROUP="accel", MODE="0660"' ${pkgs.omarchy-ane-tools}/lib/udev/rules.d/70-omarchy-ane.rules
     touch $out
   ''
