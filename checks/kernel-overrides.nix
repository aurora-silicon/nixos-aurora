{ pkgs }:
let
  inherit (pkgs) lib;
  base = pkgs.linux-asahi.kernel;
  withPatch = patch: (pkgs.linux-asahi.override {
    _kernelPatches = [ ({ name = "aurora-config-override-test"; patch = null; } // patch) ];
  }).kernel;
  structured = withPatch { structuredExtraConfig.DUMMY = lib.kernel.no; };
  legacy = withPatch { extraConfig = "DUMMY n"; };
  repeated = withPatch { extraConfig = "DUMMY m\nDUMMY n"; };
  commented = withPatch { extraConfig = "# Disable the optional network device\nDUMMY n # owner override"; };
  forced = (pkgs.linux-asahi.override {
    _kernelPatches = [
      { name = "request-dummy"; patch = null; structuredExtraConfig.DUMMY = lib.kernel.yes; }
      { name = "force-no-dummy"; patch = null; structuredExtraConfig.DUMMY = lib.mkForce lib.kernel.no; }
    ];
  }).kernel;
  hostname = withPatch { structuredExtraConfig.DEFAULT_HOSTNAME = lib.kernel.freeform "custom-host"; };
  legacyHostname = withPatch { extraConfig = "DEFAULT_HOSTNAME custom-host"; };
  quotedHostname = withPatch { extraConfig = ''DEFAULT_HOSTNAME "custom # host" # keep the quoted hash''; };
  optional = withPatch {
    structuredExtraConfig.AURORA_TEST_ABSENT = lib.kernel.option lib.kernel.yes;
  };
  optionalDisabled = withPatch { structuredExtraConfig.DUMMY = lib.kernel.option lib.kernel.yes; };
  missingRequired = withPatch { structuredExtraConfig.DM_CRYPT = lib.kernel.no; };
  feature = withPatch { features.auroraTest = true; };
  inner = base.override {
    kernelPatches = [ {
      name = "inner-kernel-override";
      patch = null;
      structuredExtraConfig.DUMMY = lib.kernel.no;
      features.auroraInner = true;
    } ];
  };
  afterAttrs = (base.overrideAttrs (old: {
    passthru = old.passthru // { auroraOverrideAttrs = true; };
    postConfigure = old.postConfigure + ''
      touch "$TMPDIR/aurora-override-attrs"
    '';
  })).override (args: {
    inherit (inner) kernelPatches;
    features = args.features // { auroraCallback = true; };
    extraMakeFlags = args.extraMakeFlags ++ [ "AURORA_TEST_CALLBACK=1" ];
  });
  sourceFragments = pkgs.runCommand "aurora-kernel-configure-test-source" { } ''
    mkdir -p $out
    tar -xzf ${base.src} -C $out --strip-components=1 --wildcards \
      '*/scripts/kconfig/merge_config.sh' '*/arch/arm64/configs/asahi.config'
  '';
  # Only Kbuild resolution is simulated. The actual configurePhase must copy
  # the canonical base and merge NixOS and owner fragments with the pinned
  # kernel's merge_config.sh before these synthetic dependency changes apply.
  resolveFixture = pkgs.writeText "resolve-kernel-fixture.py" ''
    from pathlib import Path
    import sys
    lines = {}
    config = Path(sys.argv[1])
    for path in [config, Path(sys.argv[2])]:
        for line in path.read_text().splitlines():
            if line.startswith('CONFIG_'):
                lines[line.split('=', 1)[0]] = line
            elif line.startswith('# CONFIG_') and line.endswith(' is not set'):
                lines[line.split()[1]] = line
    lines.pop('CONFIG_AURORA_TEST_ABSENT', None)
    config.write_text('\n'.join(lines.values()) + '\n')
  '';
  configureHook = name: kernel: changes: pkgs.writeShellScript "kernel-configure-${name}" ''
    set -euo pipefail
    makeFlags=()
    buildFlags=()
    export SOURCE_DATE_EPOCH=1
    sourceDirectory="$PWD"
    postConfigure() {
      ${kernel.postConfigure}
    }
    runHook() {
      case "$1" in
        preConfigure) : ;;
        postConfigure) postConfigure ;;
        *) return 1 ;;
      esac
    }
    make() {
      echo "$1" >> "$NIX_BUILD_TOP/make-calls"
      case "$1" in
        olddefconfig)
          cp "$buildRoot/.config" "$NIX_BUILD_TOP/merged.config"
          python3 ${resolveFixture} "$buildRoot/.config" ${pkgs.writeText "kconfig-result-${name}" changes}
          ;;
        certs/)
          mkdir -p "$buildRoot/certs"
          printf '#!${pkgs.runtimeShell}\n: > "$2"\n' > "$buildRoot/certs/extract-cert"
          chmod +x "$buildRoot/certs/extract-cert"
          ;;
        prepare)
          mkdir -p "$buildRoot/include/config" "$buildRoot/arch/arm64"
          echo "fixture vmlinux" > "$buildRoot/vmlinux"
          echo ${lib.escapeShellArg base.version} > "$buildRoot/include/config/kernel.release"
          ;;
        rustavailable|clean) : ;;
        outputmakefile) printf 'KBUILD_OUTPUT=%s\n' "$buildRoot" > "$buildRoot/Makefile" ;;
        *) return 1 ;;
      esac
    }
    ${kernel.configurePhase}
    test "$PWD" = "$sourceDirectory"
    test "$buildRoot" = "$NIX_BUILD_TOP/build"
    test ! -e "$sourceDirectory/build"
    ${kernel.postInstall}
    test ! -e "$NIX_BUILD_TOP/build"
    test -s "$dev/lib/modules/${base.modDirVersion}/build/.config"
    test -f "$dev/lib/modules/${base.modDirVersion}/source/Makefile"
    test "$(readlink "$dev/vmlinux")" = "$dev/lib/modules/${base.modDirVersion}/build/vmlinux"
    grep -qxF "KBUILD_OUTPUT=$dev/lib/modules/${base.modDirVersion}/build" "$dev/lib/modules/${base.modDirVersion}/build/Makefile"
    test "$(cat "$modules/lib/modules/${base.modDirVersion}/modules.cer")" = 'fixture certificate'
    test ! -e "$modules/lib/modules/${base.modDirVersion}/fixture.ko.cer"
    test ! -L "$modules/lib/modules/${base.modDirVersion}/build"
  '';
  exercise = name: kernel: changes: failure: ''
    (
      mkdir -p ${name}/tmp
      export NIX_BUILD_TOP="$PWD/${name}" TMPDIR="$PWD/${name}/tmp"
      export dev="$NIX_BUILD_TOP/dev" out="$NIX_BUILD_TOP/out" modules="$NIX_BUILD_TOP/modules"
      sourceDirectory="$dev/lib/modules/${base.modDirVersion}/source"
      mkdir -p "$sourceDirectory" "$out" "$modules/lib/modules/${base.modDirVersion}"
      cp -r ${sourceFragments}/. "$sourceDirectory/"
      chmod -R u+w "$sourceDirectory"
      cd "$sourceDirectory"
      mkdir -p drivers/firmware/efi/libstub rust
      echo '# fixture kernel Makefile' > Makefile
      touch drivers/firmware/efi/libstub/fixture.h rust/Makefile
      ln -s "$dev/lib/modules/${base.modDirVersion}/build" "$modules/lib/modules/${base.modDirVersion}/build"
      printf 'fixture.ko\n' > "$modules/lib/modules/${base.modDirVersion}/modules.order"
      printf 'fixture certificate\n' > "$modules/lib/modules/${base.modDirVersion}/fixture.ko.cer"
      ${if failure == null then ''
        ${configureHook name kernel changes}
        test -s "$dev/lib/modules/${base.modDirVersion}/build/include/config/kernel.release"
        test -f "$TMPDIR/aurora-empty-cert"
        printf 'olddefconfig\nrustavailable\ncerts/\nprepare\nclean\noutputmakefile\n' > "$NIX_BUILD_TOP/expected-make-calls"
        diff -u "$NIX_BUILD_TOP/expected-make-calls" "$NIX_BUILD_TOP/make-calls"
      '' else ''
        if ${configureHook name kernel changes} > failure.log 2>&1; then
          echo 'kernel validation unexpectedly accepted ${name}' >&2
          exit 1
        fi
        grep -F ${lib.escapeShellArg failure} failure.log
      ''}
    )
  '';

in
assert lib.assertMsg (base.config.isEnabled "DUMMY") "Kernel override test requires the baseline dummy driver";
assert lib.assertMsg (!structured.config.isEnabled "DUMMY" && structured.drvPath != base.drvPath)
  "Kernel structuredExtraConfig must affect both build inputs and option metadata";
assert lib.assertMsg (!legacy.config.isEnabled "DUMMY" && legacy.drvPath != base.drvPath)
  "Kernel legacy extraConfig must affect both build inputs and option metadata";
assert lib.assertMsg (!repeated.config.isEnabled "DUMMY")
  "Later legacy kernel settings must override earlier ones";
assert lib.assertMsg (!forced.config.isEnabled "DUMMY")
  "Structured kernel settings must preserve mkForce priorities";
assert lib.assertMsg (hostname.config.getValue "DEFAULT_HOSTNAME" == ''"custom-host"'')
  "Bare string kernel settings must be quoted in Kconfig format";
assert lib.assertMsg (optional.drvPath != base.drvPath)
  "Optional kernel settings must reach Kconfig";
assert lib.assertMsg (!optional.config.isEnabled "AURORA_TEST_ABSENT"
  && !optionalDisabled.config.isEnabled "DUMMY")
  "Optional requests must not advertise unverified capabilities to NixOS";
assert lib.assertMsg (!commented.config.isEnabled "DUMMY")
  "Legacy configuration comments must not become setting values";
assert lib.assertMsg (feature.features.auroraTest or false)
  "Kernel patch feature metadata must be preserved";
assert lib.assertMsg (!inner.config.isEnabled "DUMMY" && inner.features.auroraInner)
  "Inner kernel overrides must regenerate config and patch features";
assert lib.assertMsg ((inner.override { inherit (base) kernelPatches; }).drvPath == base.drvPath)
  "Restoring the baseline kernel patches must restore the baseline derivation";
assert lib.assertMsg (afterAttrs.auroraOverrideAttrs && afterAttrs.features.auroraCallback
  && !afterAttrs.config.isEnabled "DUMMY" && lib.elem "AURORA_TEST_CALLBACK=1" afterAttrs.makeFlags)
  "Kernel override callbacks and overrideAttrs must remain composable";
pkgs.runCommand "aurora-kernel-overrides" { nativeBuildInputs = [ pkgs.python3 ]; } ''
  ${exercise "base" base "" null}
  ${exercise "structured" structured "" null}
  ${exercise "inner-structured" inner "" null}
  ${exercise "inner-after-attrs" afterAttrs "" null}
  test -f inner-after-attrs/tmp/aurora-override-attrs
  ${exercise "forced" forced "" null}
  ${exercise "legacy" legacy "" null}
  ${exercise "repeated" repeated "" null}
  ${exercise "commented" commented "" null}
  ${exercise "hostname" hostname "" null}
  ${exercise "legacy-hostname" legacyHostname "" null}
  ${exercise "quoted-hostname" quotedHostname "" null}
  ${exercise "optional-absent" optional "" null}
  ${exercise "optional-disabled" optionalDisabled "# CONFIG_DUMMY is not set\n" null}
  ${exercise "optional-enabled" optionalDisabled "" null}
  ${exercise "mandatory-mismatch" structured "CONFIG_DUMMY=m\n" "CONFIG_DUMMY: wanted n, got m"}
  ${exercise "hardware-capability" base "# CONFIG_APPLE_SEP is not set\n" "CONFIG_APPLE_SEP: wanted m, got n"}
  ${exercise "required-capability" missingRequired "" "CONFIG_DM_CRYPT"}
  python3 - ${../kernel/config} ${../kernel/nixos.config} base/dev/lib/modules/${base.modDirVersion}/build/.config <<'PY'
  from pathlib import Path
  import sys
  def values(paths):
      result = {}
      for path in paths:
          for line in Path(path).read_text().splitlines():
              if line.startswith('CONFIG_'):
                  name, value = line.split('=', 1)
                  result[name] = value
              elif line.startswith('# CONFIG_') and line.endswith(' is not set'):
                  result[line.split()[1]] = 'n'
      return result
  assert values(sys.argv[1:3]) == values(sys.argv[3:]), 'canonical/NixOS merge differs'
  PY
  touch $out
''
