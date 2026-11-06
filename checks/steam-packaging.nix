{ pkgs, self, nixpkgs }:
let
  inherit (nixpkgs) lib;
  graphicsFixture = pkgs.runCommandCC "steam-configured-graphics-fixture" {} ''
    mkdir -p "$out/lib"
    printf '%s\n' 'int aurora_graphics_fixture(void) { return 42; }' > driver.c
    $CC -shared -fPIC -Wl,-soname,libaurora_fixture.so driver.c -o "$out/lib/libaurora_fixture.so"
  '';
  system = self.nixosConfigurations.aurora-minimal.extendModules {
    modules = [ ({ lib, ... }: {
      programs.steam.enable = true;
      programs.steam.package = pkgs.steam.override {
        extraEnv.AURORA_STEAM_CONFIGURED = "module-selected";
      };
      # Exercise NixOS's driver injection with a real, tiny shared library.
      # Hardware-package CI independently builds the actual Mesa variants.
      hardware.graphics.package = lib.mkForce graphicsFixture;
      hardware.graphics.extraPackages = lib.mkForce [];
    }) ];
  };
  cfg = system.config;
  failures = map (value: value.message) (builtins.filter (value: !value.assertion) cfg.assertions);
  steam = cfg.programs.steam.package;
  customTool = pkgs.writeTextDir "user_settings.py" "fixture compatibility tool\n";
  customSystem = system.extendModules {
    modules = [ { programs.steam.extraCompatPackages = [ customTool ]; } ];
  };
  disabledSystem = system.extendModules {
    modules = [ ({ lib, ... }: {
      programs.steam.package = lib.mkForce (pkgs.steam.override {
        proton = null;
        extraEnv.AURORA_STEAM_CONFIGURED = "module-selected";
      });
    }) ];
  };
  payload = pkgs.runCommandCC "steam-native-entry-fixture" {} ''
    $CC -Wall -Wextra -Werror ${./steam-payload.c} -o "$out"
  '';
  # General CI kernels already use 4 KiB pages and lack Aurora's private
  # prctl. On a 16 KiB Aurora host use the actual launcher; in both cases
  # the real ELF parent and Python descendant verify their own page sizes.
  pageLauncher = pkgs.writeShellScript "steam-fixture-page-launcher" ''
    [ "$1" = 4k ] || exit 64
    shift
    if [ "$(${pkgs.glibc.bin}/bin/getconf PAGE_SIZE)" = 4096 ]; then
      exec "$@"
    fi
    exec ${pkgs.aurora-userpages}/bin/userpages 4k "$@"
  '';
  runtimeConfig = pkgs.writeText "steam-runtime-fixture.json" (builtins.toJSON {
    inherit payload pageLauncher;
    probe = ./steam-runtime-probe.py;
    proton = pkgs.aurora-proton;
    configuredCompat = lib.makeSearchPathOutput "steamcompattool" "" [ customTool ];
    packages = {
      default = steam;
      configured-custom = customSystem.config.programs.steam.package;
      disabled = disabledSystem.config.programs.steam.package;
    };
  });
in
assert lib.assertMsg (failures == [ ]) "Aurora Steam module: ${lib.concatStringsSep "; " failures}";
assert !cfg.hardware.graphics.enable32Bit;
assert !cfg.services.pipewire.alsa.support32Bit;
assert !cfg.services.pulseaudio.support32Bit;
pkgs.runCommand "aurora-steam-packaging" {
  nativeBuildInputs = [ pkgs.python3 ];
} ''
  export HOME="$TMPDIR/home" XDG_DATA_HOME="$TMPDIR/data"
  mkdir -p "$HOME" "$XDG_DATA_HOME"
  test -x ${steam}/bin/steam
  test -x ${steam}/bin/aurora-play
  grep -qx 'Exec=aurora-play' ${steam}/share/applications/org.aurorasilicon.Play.desktop
  ${steam}/bin/aurora-play --help > /dev/null
  test ! -e "$XDG_DATA_HOME/aurora-proton"
  test -x ${pkgs.aurora-proton}/proton
  test -f ${pkgs.aurora-proton}/files/bin/wine
  cmp ${pkgs.aurora-proton.patchedNtdll}/lib/ntdll.so \
    ${pkgs.aurora-proton}/files/lib/wine/aarch64-unix/ntdll.so
  grep -q 'Aurora-Proton${pkgs.aurora-proton.version}' ${pkgs.aurora-proton}/compatibilitytool.vdf
  ${pkgs.python3}/bin/python3 ${../steam/test-play.py} \
    ${pkgs.steam-unwrapped}/lib/aurora-steam-native/bin/.aurora-play-wrapped ${pkgs.aurora-proton}
  ${pkgs.python3}/bin/python3 ${../steam/test-installer.py} \
    ${pkgs.steam-unwrapped}/lib/aurora-steam-native/install-steam-arm64.py
  python3 ${./steam-runtime.py} ${runtimeConfig}
  ${pkgs.python3}/bin/python3 - ${steam.fhsenv} <<'PY'
import json, pathlib, struct, sys
root = pathlib.Path(sys.argv[1])
manifests = list((root / 'usr/share/vulkan/implicit_layer.d').glob('*[Mm]ango[Hh]ud*.json'))
assert manifests, 'Steam must include the native MangoHud Vulkan layer for Play Stats'
for manifest in manifests:
    layer = json.loads(manifest.read_text())['layer']
    library = pathlib.Path(layer['library_path'])
    if not library.is_absolute():
        library = manifest.parent / library
    header = library.read_bytes()[:20]
    assert header[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', header, 18)[0] == 183, library
PY
  touch $out
''
