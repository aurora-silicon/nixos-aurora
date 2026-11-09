# Aurora's steam-unwrapped: the aurora-steam-native launcher for Valve's
# native ARM64 Linux client, wrapped by nixpkgs' steam FHS environment.
# The first start installs Valve's client for the user from Valve's CDN.
{ lib, stdenvNoCC, bash, python3, aurora-userpages, desktop-file-utils
, gtk4, libadwaita, wrapGAppsHook4, gobject-introspection, makeWrapper, src, commit }:
let
  playPython = python3.withPackages (p: [ p.pygobject3 ]);
in
stdenvNoCC.mkDerivation {
  pname = "steam-unwrapped";
  version = "0-aurora-${builtins.substring 0 7 commit}";
  inherit src;
  nativeBuildInputs = [ desktop-file-utils wrapGAppsHook4 gobject-introspection makeWrapper ];
  patches = [ ./aurora-play-nixos.patch ];
  dontWrapGApps = true;
  buildInputs = [ bash python3 gtk4 libadwaita ];
  nativeCheckInputs = [ python3 ];
  postPatch = ''
    find . -name __pycache__ -prune -exec rm -rf {} +
    # The loop re-enters bash inside the 4 KiB tree by absolute path.
    substituteInPlace libexec/steam-native4k-launch-loop.sh \
      --replace-fail 'exec "$AURORA_USERPAGES_LAUNCHER" 4k /bin/bash -c' \
                     'exec "$AURORA_USERPAGES_LAUNCHER" 4k ${bash}/bin/bash -c'
    patchShebangs --host bin libexec install-steam-arm64.py
    sed -i '1c#!${playPython}/bin/python3' bin/aurora-play
    patchShebangs --build tests
    # The test's userpages stand-in is a bash script; the build sandbox has no /bin/bash.
    substituteInPlace tests/test-steam-native4k-launch-env.py --replace-fail '#!/bin/bash' '#!${bash}/bin/bash'
  '';
  dontBuild = true;
  installPhase = ''
    runHook preInstall
    lib=$out/lib/aurora-steam-native
    install -Dm755 install-steam-arm64.py $lib/install-steam-arm64.py
    install -Dm755 bin/steam-native4k $lib/bin/steam-native4k
    install -Dm755 bin/aurora-play $lib/bin/aurora-play
    install -Dm755 libexec/steam-native4k-launch-loop.sh $lib/libexec/steam-native4k-launch-loop.sh
    for f in share/applications/steam-native-arm64.desktop share/applications/org.aurorasilicon.Play.desktop \
        share/icons/hicolor/scalable/apps/org.aurorasilicon.Play.svg; do
      install -Dm644 $f $lib/$f
    done
    sed -e "s,@LIBDIR@,$lib," -e "s,@USERPAGES@,${aurora-userpages}/bin/userpages," \
      -e 's|@USER4K_HINT@|keep aurora.userpages.enable on (it adds user4k=on to boot.kernelParams), rebuild and reboot|' \
      ${./steam} > $out/bin-steam
    # NixOS mounts the FEX guest graphics provider (aurora.fexMesa) here,
    # not at the launch loop's /usr/share/guestos default.
    sed -i '/^exec "\$lib\/bin\/steam-native4k" "\$@"$/i export AURORA_FEX_GRAPHICS_PROVIDER=''${AURORA_FEX_GRAPHICS_PROVIDER:-/var/lib/aurora/fex/mesa-rootfs/graphics_provider.json}' $out/bin-steam
    grep -qx 'export AURORA_FEX_GRAPHICS_PROVIDER=''${AURORA_FEX_GRAPHICS_PROVIDER:-/var/lib/aurora/fex/mesa-rootfs/graphics_provider.json}' $out/bin-steam
    if grep -n '@[A-Z0-9_]*@' $out/bin-steam; then exit 1; fi
    install -Dm755 $out/bin-steam $out/bin/steam && rm $out/bin-steam
    ln -s $lib/bin/aurora-play $out/bin/aurora-play
    install -Dm644 ${./steam.desktop} $out/share/applications/steam.desktop
    install -Dm644 share/applications/org.aurorasilicon.Play.desktop $out/share/applications/org.aurorasilicon.Play.desktop
    install -Dm644 share/icons/hicolor/scalable/apps/org.aurorasilicon.Play.svg \
      $out/share/icons/hicolor/scalable/apps/org.aurorasilicon.Play.svg
    runHook postInstall
  '';
  preFixup = ''
    wrapProgram $out/lib/aurora-steam-native/bin/aurora-play "''${gappsWrapperArgs[@]}"
  '';
  doInstallCheck = true;
  installCheckPhase = ''
    runHook preInstallCheck
    HOME="$TMPDIR/play-home" $out/bin/aurora-play --help > /dev/null
    runHook postInstallCheck
  '';
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    desktop-file-validate ${./steam.desktop} share/applications/org.aurorasilicon.Play.desktop
    for t in tests/test-steam-native4k-launch-env.py tests/test-offline-installer.py tests/test-aurora-play-settings.py; do
      python3 -I "$t"
    done
    python3 ${./test-play.py} bin/aurora-play
    python3 ${./test-installer.py} install-steam-arm64.py
    runHook postCheck
  '';
  passthru = { inherit commit; };
  meta = {
    description = "Valve's native ARM64 Steam client in a 4 KiB page process tree (Aurora)";
    homepage = "https://github.com/aurora-silicon/aurora-steam-native";
    license = lib.licenses.mit;
    mainProgram = "steam";
    platforms = [ "aarch64-linux" ];
  };
}
