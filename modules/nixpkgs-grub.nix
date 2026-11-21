# nixpkgs' install-grub.pl, which writes /boot/grub/grub.cfg, loads efi_gop
# and efi_uga on every EFI GRUB. UGA is an x86-only EFI protocol: arm64-efi
# GRUB has no efi_uga module, and every boot printed "error: ... file
# '/grub/arm64-efi/efi_uga.mod' not found." on the screen. The script is a
# file of nixpkgs' GRUB module, not a package, so this disables that module
# and imports the same file again with the script patched
# (patches/nixpkgs-install-grub-efi-uga.patch).
#
# Upstream change: "nixpkgs install-grub.pl: write insmod efi_uga only for
# x86 EFI targets". Remove this module and the patch once the pinned nixpkgs
# has it (the patch then no longer applies).
{ modulesPath, ... }:
let
  grubModule = import "${modulesPath}/system/boot/loader/grub/grub.nix";
  installGrub = "${modulesPath}/system/boot/loader/grub/install-grub.pl";
  patched = pkgs: src: pkgs.runCommand "nixpkgs-install-grub" { } ''
    mkdir "$out"
    cp ${src} "$out/install-grub.pl"
    chmod u+w "$out/install-grub.pl"
    patch "$out/install-grub.pl" ${../patches/nixpkgs-install-grub-efi-uga.patch}
  '';
in
{
  disabledModules = [ "system/boot/loader/grub/grub.nix" ];
  imports = [
    # The module makes its install script with pkgs.replaceVars ./install-grub.pl.
    # config, options and lib reach it in args; pkgs is named to be passed.
    ({ pkgs, ... }@args: grubModule (args // {
      pkgs = pkgs // {
        replaceVars = src: pkgs.replaceVars
          (if toString src == installGrub then "${patched pkgs src}/install-grub.pl" else src);
      };
    }))
  ];
}
