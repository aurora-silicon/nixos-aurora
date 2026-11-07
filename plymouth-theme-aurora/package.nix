{ stdenvNoCC, lib, plymouth, python3 }:
# The Aurora boot splash: aura's logo at aura's size and place (128 or 256 px,
# centred, in device pixels), the spinner below it and the distribution's
# branding at the bottom. The script reads its spinner, entry and watermark
# images from the spinner theme; boot.plymouth's initrd copies that theme
# because the theme file names it, with boot.plymouth.logo as its watermark.
assert lib.assertMsg ((plymouth.scriptKeyboardLifetime or 0) >= 1)
  "Aurora requires Plymouth script keyboard lifetime capability >= 1";
stdenvNoCC.mkDerivation {
  pname = "plymouth-theme-aurora";
  version = "1-4";
  src = ./.;
  dontBuild = true;
  doCheck = true;
  nativeCheckInputs = [ python3 ];
  propagatedBuildInputs = [ plymouth ];
  checkPhase = "python3 test_geometry.py .";
  installPhase = ''
    runHook preInstall
    d=$out/share/plymouth/themes/aurora
    install -Dm644 aurora.plymouth $d/aurora.plymouth
    substituteInPlace $d/aurora.plymouth \
      --replace-fail "ImageDir=/usr/share/plymouth/themes/spinner" "ImageDir=/run/plymouth/themes/spinner"
    # NixOS discovers dependent themes through /share/plymouth/themes paths.
    # Keep that discovery while ImageDir uses the merged runtime theme tree.
    echo '# NixOS dependent theme: /share/plymouth/themes/spinner' >> $d/aurora.plymouth
    install -Dm644 aurora.script $d/aurora.script
    install -Dm644 aurora-logo-128.png $d/aurora-logo-128.png
    install -Dm644 aurora-logo-256.png $d/aurora-logo-256.png
    install -Dm755 aurora-plymouth $out/libexec/aurora-plymouth
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
