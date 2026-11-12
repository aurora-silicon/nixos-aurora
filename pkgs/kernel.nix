{ lib, callPackage, path, writeText, llvmPackages, openssl, binutils, aurora-bindgen
, src, pin, kernelCtxrExecmem, kernelDtbAbi, kernelPatches ? [ ] }:
let
  stableFile = path: writeText (builtins.baseNameOf path) (builtins.readFile path);
  kernelProvenance = builtins.fromJSON (builtins.readFile ../kernel/provenance.json);
  kernelBase =
    assert lib.assertMsg
      (kernelProvenance.kernel_commit == pin.commit
        && kernelProvenance.config_upstream.kernel_commit == kernelProvenance.kernel_commit)
      "Refresh the canonical ALARM resolved config together with the kernel pin";
    assert lib.assertMsg
      (builtins.hashFile "sha256" ../kernel/config == kernelProvenance.config_upstream.config_sha256)
      "The vendored ALARM resolved config does not match its provenance";
    builtins.readFile ../kernel/config;
  kernelBaseFile = writeText "config" kernelBase;
  baseConfig = lib.listToAttrs (lib.concatMap (line:
    let matched = builtins.match "(CONFIG_[^=]+)=([ym])" line;
    in lib.optional (matched != null) {
      name = builtins.elemAt matched 0; value = builtins.elemAt matched 1;
    }) (lib.splitString "\n" (kernelBase + "\n" + builtins.readFile ../kernel/nixos.config)));
  # Keep the complete builder argument set available to .override callbacks.
  # Recompute owner fragments when the inner kernel's patch list changes too.
  buildKernel = args:
    let
      overrides = import ../kernel/overrides.nix {
        inherit lib writeText;
        inherit (args) kernelPatches;
        nixpkgsPath = path;
      };
      inherit (overrides) requests configOverrides requiredOverrides optionalRequests optionalDefaults optionalPattern;
      # Optional requests must not advertise capabilities Kconfig may disable.
      config = builtins.removeAttrs args.config (map (request: request.name) optionalRequests)
        // overrides.guaranteedConfig;
      features = lib.foldr (patch: features: (patch.features or { }) // features)
        args.features args.kernelPatches;
    in ((callPackage (path + "/pkgs/os-specific/linux/kernel/build.nix") {
      rust-bindgen-unwrapped = aurora-bindgen;
    }) (args // { inherit config features; })).overrideAttrs (finalAttrs: old: {
      # NixOS consumers (including ASLR limits) need the resolved config,
      # which the kernel builder already installs in its development output.
      # Keep the configure input fragment private to the build environment.
      passthru = old.passthru // {
        configfile = "${finalAttrs.finalPackage.dev}/lib/modules/${old.passthru.modDirVersion}/build/.config";
        # Installed generations check Aura compatibility and record the DT ABI.
        auroraCtxrExecmem = kernelCtxrExecmem;
        auroraDtbAbi = kernelDtbAbi;
        auroraLegacySpeakerProtection = true;
        # Source overrides must not keep advertising the packaged revision.
        auroraSourceCommit = finalAttrs.src.rev or null;
      };
      env = old.env // { RUSTC_BOOTSTRAP = "1"; };
      nativeBuildInputs = old.nativeBuildInputs ++ [ binutils llvmPackages.lld ];
      # The source-tree entry point is selected by the pinned Kbuild.
      postPatch = (old.postPatch or "") + ''
        mkdir -p tools/aurora-bindgen/build/bin
        ln -s ${aurora-bindgen}/bin/bindgen tools/aurora-bindgen/build/bin/bindgen
      '';
      # Start from the resolved configuration alarm-aurora ships for this
      # kernel (kernel/config, see kernel/provenance.json), so every
      # distribution builds the same options, and add only NixOS's own
      # requirements on top.
      configurePhase = ''
        runHook preConfigure
        # nixpkgs retains this tree beside source/ in the development output.
        # Its postInstall move must not target the build directory itself.
        export buildRoot="$NIX_BUILD_TOP/build"
        mkdir -- "$buildRoot"
        cp ${kernelBaseFile} "$buildRoot/.config"
        chmod u+w "$buildRoot/.config"
        bash scripts/kconfig/merge_config.sh -m -O "$buildRoot" \
          "$buildRoot/.config" ${stableFile ../kernel/nixos.config}${lib.optionalString (requests != [ ]) " ${configOverrides}"}
        make "''${makeFlags[@]}" olddefconfig
        runHook postConfigure
        make "''${makeFlags[@]}" prepare
        test "$(cat "$buildRoot/include/config/kernel.release")" = ${pin.version}
        buildFlags+=("KBUILD_BUILD_TIMESTAMP=$(date -u -d @$SOURCE_DATE_EPOCH)")
      '';
      postConfigure = lib.optionalString (optionalRequests != [ ]) ''
        # Optional requests may be absent or disabled by Kconfig dependencies.
        # Relax their base-config expectations to the resolved values only;
        # mandatory requests below must still match exactly.
        cat ${optionalDefaults} > "$TMPDIR/aurora-kernel-optional.config"
        grep -E ${lib.escapeShellArg "^(${optionalPattern})=|^# (${optionalPattern}) is not set$"} \
          "$buildRoot/.config" >> "$TMPDIR/aurora-kernel-optional.config" || true
      '' + ''
        python3 ${stableFile ../kernel/validate-config.py} arch/arm64/configs/asahi.config \
          ${stableFile ../kernel/nixos.config}${lib.optionalString (optionalRequests != [ ]) " \"$TMPDIR/aurora-kernel-optional.config\""}${lib.optionalString (requests != [ ]) " ${requiredOverrides}"} "$buildRoot/.config"
        python3 ${stableFile ../kernel/check-required.py} "$buildRoot/.config"
        grep -qx 'CONFIG_RUST=y' "$buildRoot/.config"
        grep -qx 'CONFIG_ARM64_16K_PAGES=y' "$buildRoot/.config"
        ctxr=false
        if grep -qx 'CONFIG_ARM64_CTXR_EXECMEM=y' "$buildRoot/.config"; then ctxr=true; fi
        if [ "$ctxr" != ${lib.boolToString kernelCtxrExecmem} ]; then
          echo "overlay.nix: set kernelCtxrExecmem = $ctxr; which this pin's configuration resolves to" >&2
          exit 1
        fi
        make "''${makeFlags[@]}" rustavailable
        make "''${makeFlags[@]}" certs/
        "$buildRoot/certs/extract-cert" "" "$TMPDIR/aurora-empty-cert"
      '';
      # Kbuild signs the modules with the key this build puts in the kernel, as on
      # ALARM and Fedora. nixpkgs' kmodigest signatures need CRYPTO_ECDSA and their
      # certificates in the image, which this configuration doesn't have.
      makeFlags = lib.filter (flag: !lib.hasPrefix "cmd_sign=" flag) old.makeFlags;
      # INSTALL_MOD_STRIP strips each module before it's signed; stripping it again
      # would drop the signature.
      stripExclude = old.stripExclude ++ [ "*.ko" ];
      # nixpkgs folds each module's kmodigest certificate into modules.cer, so give
      # it empty ones. The signing key stays in the build tree it keeps in $dev and
      # must not reach the store.
      postInstall = ''
        if [[ -v modules ]]; then
          (cd -- "$modules/lib/modules/${old.passthru.modDirVersion}" &&
            sed 's/$/.cer/' modules.order | xargs -r -d'\n' touch --)
        fi
      '' + (old.postInstall or "") + ''
        if [[ -v modules ]]; then
          # Every module carries a signature from the certificate built into this
          # kernel: sign-file names it by serial number, or by key ID with -k.
          cert="$dev/lib/modules/${old.passthru.modDirVersion}/build/certs/signing_key.x509"
          hexid() { tr -d ' :\t\n' | tr a-f A-F | sed 's/^0*//'; }
          serial=$(openssl x509 -inform DER -in "$cert" -noout -serial | cut -d= -f2 | hexid)
          skid=$(openssl x509 -inform DER -in "$cert" -noout -ext subjectKeyIdentifier | tail -n 1 | hexid)
          signed=0 bad=0
          while IFS= read -r -d "" ko; do
            key=$(modinfo -F sig_key "$ko" | hexid)
            if [[ "$(tail -c 28 "$ko")" == "~Module signature appended~" && -n $key &&
                  ( $key == "$serial" || $key == "$skid" ) ]]; then
              signed=$((signed + 1))
            else
              echo "module not signed by the built-in certificate: $ko" >&2
              bad=$((bad + 1))
            fi
          done < <(find "$modules/lib/modules/${old.passthru.modDirVersion}" -name '*.ko' -print0)
          echo "modules signed by the built-in certificate (serial $serial): $signed, other: $bad"
          if (( signed == 0 || bad > 0 )); then
            exit 1
          fi
        fi
        rm -f -- "$dev/lib/modules/${old.passthru.modDirVersion}/build/certs/signing_key.pem"
        printf '%s\n' ${lib.escapeShellArg (finalAttrs.src.rev or "unknown")} > "$out/aurora-source-commit"
      '';
    });
in lib.makeOverridable buildKernel {
  pname = "linux-aurora";
  inherit (pin) version;
  modDirVersion = pin.version;
  inherit src;
  configfile = kernelBaseFile;
  config = baseConfig;
  inherit (llvmPackages) stdenv;
  # Keep the native wrapped host compiler for host tools/RPATHs;
  # compile the Apple kernel and Rust bindings with pinned LLVM.
  extraMakeFlags = [ "LLVM=1" "LOCALVERSION=" "HOSTLDFLAGS=-fuse-ld=bfd -Wl,-rpath,${lib.getLib openssl}/lib"
    "CC=${llvmPackages.clang-unwrapped}/bin/clang"
    "LD=${llvmPackages.lld}/bin/ld.lld"
    "AR=${llvmPackages.llvm}/bin/llvm-ar"
    "NM=${llvmPackages.llvm}/bin/llvm-nm"
    "STRIP=${llvmPackages.llvm}/bin/llvm-strip"
    "OBJCOPY=${llvmPackages.llvm}/bin/llvm-objcopy"
    "OBJDUMP=${llvmPackages.llvm}/bin/llvm-objdump"
    "READELF=${llvmPackages.llvm}/bin/llvm-readelf"
    "CFLAGS_MODULE=-I${lib.getLib llvmPackages.clang-unwrapped}/lib/clang/${lib.versions.major llvmPackages.clang-unwrapped.version}/include"
    "CFLAGS_KERNEL=-I${lib.getLib llvmPackages.clang-unwrapped}/lib/clang/${lib.versions.major llvmPackages.clang-unwrapped.version}/include"
  ];
  extraMeta.branch = lib.versions.majorMinor pin.version;
  features.rust = true;
  inherit kernelPatches;
}
