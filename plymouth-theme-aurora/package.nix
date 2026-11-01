{ stdenvNoCC, lib, plymouth }:
# The Aurora boot splash: the 256 px logo aura (Stage 1) draws centred on Retina
# panels, drawn again at the same place on black, with the spinner below it.
stdenvNoCC.mkDerivation {
  pname = "plymouth-theme-aurora";
  version = "1";
  src = ./.;
  dontBuild = true;
  installPhase = ''
    runHook preInstall
    d=$out/share/plymouth/themes/aurora
    install -Dm644 aurora.plymouth $d/aurora.plymouth
    substituteInPlace $d/aurora.plymouth \
      --replace-fail "ImageDir=/usr/share/plymouth/themes/aurora" "ImageDir=$d"
    install -Dm644 aurora-logo-256.png $d/watermark.png
    # two-step reads every image from ImageDir. The NixOS initrd copies the theme
    # directory without following links, so take real copies of the spinner
    # theme's animation and dialog images.
    for f in ${plymouth}/share/plymouth/themes/spinner/*.png; do
      [ "''${f##*/}" = watermark.png ] && continue
      install -m644 "$f" "$d/''${f##*/}"
    done
    install -Dm644 LICENSE $out/share/licenses/plymouth-theme-aurora/LICENSE
    runHook postInstall
  '';
  meta = {
    description = "Aurora boot splash: the bootloader logo, kept in place, with a spinner";
    homepage = "https://aurorasilicon.org";
    license = lib.licenses.mit;
    platforms = lib.platforms.all;
  };
}
