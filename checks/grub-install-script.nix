# Every profile's bootloader install runs nixpkgs' install-grub.pl with
# patches/nixpkgs-install-grub-efi-uga.patch (modules/nixpkgs-grub.nix): it
# compiles, and the grub.cfg it writes loads efi_uga only on x86 EFI GRUB.
{ pkgs, nixpkgs, self }:
let
  inherit (nixpkgs) lib;
  # Stage 2 off keeps the kernel and aura out of the install script's
  # closure; the GRUB module and its install-grub.pl are the same.
  installers = map (profile: (profile.extendModules {
    modules = [ { aurora.stage2.enable = false; } ];
  }).config.system.build.installBootLoader) (lib.attrValues self.nixosConfigurations);
in
pkgs.runCommand "aurora-grub-install-script" { } ''
  for installer in ${lib.concatStringsSep " " installers}; do
    read -r perl script < <(grep -oE '/nix/store/[^ ]+/bin/perl /nix/store/[^ ]+install-grub\.pl' "$installer" | head -n1)
    test -n "$script"
    "$perl" -c "$script"
    "$perl" ${./grub-video.pl} "$script" arm64-efi > arm64.cfg
    "$perl" ${./grub-video.pl} "$script" x86_64-efi > x86_64.cfg
    grep -qx '      insmod efi_gop' arm64.cfg
    if grep -q efi_uga arm64.cfg; then echo "$script loads efi_uga on arm64-efi" >&2; exit 1; fi
    grep -qx '      insmod efi_uga' x86_64.cfg
  done
  cat arm64.cfg
  touch "$out"
''
