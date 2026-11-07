{ self, nixpkgs, pkgs, system, overlays, makeSystem }:
let
  imageProbe = (makeSystem "minimal").extendModules {
    modules = [ ({ lib, ... }: { aurora.imageLayout = lib.mkForce {
      rootUUID = "eb688499-cc41-4c4c-b00b-dbf33e05427c";
      bootUUID = "3429647d-29a2-411c-8924-2545fda1ec34";
      efiUUID = "1E08-14ED";
    }; }) ];
  };
in (import ./nix-lint.nix { inherit pkgs; }) // {
  documentation = import ./documentation.nix { inherit pkgs nixpkgs self; };
  documentation-site = import ../docs/site.nix { inherit pkgs self system; };
  steam-packaging = import ./steam-packaging.nix { inherit pkgs self nixpkgs; };
  clean-boot = import ./clean-boot.nix { inherit pkgs nixpkgs self; };
  ane-packaging = import ./ane-packaging.nix { inherit pkgs nixpkgs system overlays; };
  touchid-pam = import ./touchid-pam.nix { inherit pkgs nixpkgs self; };
  fex-overlay-upgrade = import ./fex-overlay-upgrade.nix { inherit pkgs; };
  flatpak-sandbox = import ./flatpak-sandbox.nix { inherit pkgs; };
  fedora-parity = import ./fedora-parity.nix { inherit pkgs nixpkgs self; };
  sep-kernel-transition = import ./sep-kernel-transition.nix { inherit pkgs imageProbe; };
  stage2 = imageProbe.config.system.build.auroraStage2;
  stage2-tools = imageProbe.config.system.build.auroraStage2Tools;
  userpages = import ./userpages.nix { inherit pkgs nixpkgs self; };
  firstboot-image = import ./firstboot-image.nix { inherit pkgs nixpkgs self imageProbe; };
  firstboot-rekey = import ./firstboot-rekey.nix { inherit pkgs imageProbe self; };
  sep-lifecycle = import ./sep-lifecycle.nix { inherit pkgs; };
  peripheral-firmware = import ./peripheral-firmware.nix { inherit pkgs nixpkgs self; };
  profiles = import ./profiles.nix { inherit pkgs nixpkgs self; };
  module-composition = import ./module-composition.nix { inherit pkgs nixpkgs makeSystem; };
  package-overrides = import ./package-overrides.nix { inherit pkgs; };
  kernel-overrides = import ./kernel-overrides.nix { inherit pkgs; };
  bootloader-overrides = import ./bootloader-overrides.nix { inherit pkgs; };
}
