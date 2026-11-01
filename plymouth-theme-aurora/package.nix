{ stdenvNoCC, lib, plymouth }:
# The Aurora boot splash: aura's logo at aura's size and place (128 or 256 px,
# centred, in device pixels), the spinner below it and the distribution's
# branding at the bottom. The script reads its spinner, entry and watermark
# images from the spinner theme; boot.plymouth's initrd copies that theme
# because the theme file names it, with boot.plymouth.logo as its watermark.
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
      --replace-fail "ImageDir=/usr/share/plymouth/themes/spinner" "ImageDir=${plymouth}/share/plymouth/themes/spinner" \
      --replace-fail "ScriptFile=/usr/share/plymouth/themes/aurora/aurora.script" "ScriptFile=$d/aurora.script"
    install -Dm644 aurora.script $d/aurora.script
    install -Dm644 aurora-logo-128.png $d/aurora-logo-128.png
    install -Dm644 aurora-logo-256.png $d/aurora-logo-256.png
    install -Dm644 LICENSE $out/share/licenses/plymouth-theme-aurora/LICENSE
    runHook postInstall
  '';
  meta = {
    description = "Aurora boot splash: the bootloader logo, kept in place, with the distribution's branding";
    homepage = "https://aurorasilicon.org";
    license = lib.licenses.mit;
    platforms = lib.platforms.all;
  };
}
