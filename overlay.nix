final: prev:
let
  stableFile = path: final.writeText (builtins.baseNameOf path) (builtins.readFile path);
  kernelConfig = final.lib.listToAttrs (final.lib.concatMap (line:
    let matched = builtins.match "(CONFIG_[^=]+)=([ym])" line;
    in final.lib.optional (matched != null) {
      name = builtins.elemAt matched 0; value = builtins.elemAt matched 1;
    }) (final.lib.splitString "\n" (builtins.readFile ./kernel/config)));
  kernelLLVM = final.llvmPackages_22;
  pins = builtins.fromJSON (builtins.readFile ./sources.json);
  source = name: final.fetchurl {
    name = "${name}-${pins.${name}.commit}.tar.gz";
    url = pins.${name}.source_url;
    hash = pins.${name}.nix_hash;
  };
  rustPackage = name: lock: extra: final.rustPlatform.buildRustPackage ({
    pname = name;
    version = pins.${name}.version;
    src = source name;
    cargoLock.lockFile = lock;
    doCheck = true;
  } // extra);
in {
  aurora-firstboot = final.callPackage ./firstboot.nix { };
  aurora-avd-firmware = final.callPackage ./avd-fw.nix {
    src = source "avd-fw";
    version = pins.avd-fw.version;
  };
  upower = prev.upower.overrideAttrs (old: {
    src = source "upower-aurora";
    version = pins.upower-aurora.version;
    postConfigure = (old.postConfigure or "") + ''
      meson test --list > aurora-registered-tests.txt
      grep -q test_macsmc_kernel_time_at_zero_rate aurora-registered-tests.txt
      grep -q test_other_supply_ignores_kernel_time aurora-registered-tests.txt
    '';
  });
  aurora-bindgen = final.callPackage ./bindgen { llvmPackages = kernelLLVM; };
  linux-asahi = final.lib.makeOverridable ({ _kernelPatches ? [ ] }:
    final.lib.recurseIntoAttrs (final.linuxPackagesFor (((final.callPackage
      (final.path + "/pkgs/os-specific/linux/kernel/build.nix") {
        rust-bindgen-unwrapped = final.aurora-bindgen;
      }) {
        pname = "linux-aurora";
        version = "7.2.10";
        modDirVersion = "7.2.10";
        src = source "kernel-aurora";
        configfile = stableFile ./kernel/config;
        config = kernelConfig;
        stdenv = kernelLLVM.stdenv;
        # Keep the native wrapped host compiler for host tools/RPATHs;
        # compile the Apple kernel and Rust bindings with pinned LLVM.
        extraMakeFlags = [ "LLVM=1" "LOCALVERSION=" "HOSTLDFLAGS=-fuse-ld=bfd -Wl,-rpath,${final.lib.getLib final.openssl}/lib"
          "CC=${kernelLLVM.clang-unwrapped}/bin/clang"
          "LD=${kernelLLVM.lld}/bin/ld.lld"
          "AR=${kernelLLVM.llvm}/bin/llvm-ar"
          "NM=${kernelLLVM.llvm}/bin/llvm-nm"
          "STRIP=${kernelLLVM.llvm}/bin/llvm-strip"
          "OBJCOPY=${kernelLLVM.llvm}/bin/llvm-objcopy"
          "OBJDUMP=${kernelLLVM.llvm}/bin/llvm-objdump"
          "READELF=${kernelLLVM.llvm}/bin/llvm-readelf"
          "CFLAGS_MODULE=-I${final.lib.getLib kernelLLVM.clang-unwrapped}/lib/clang/${final.lib.versions.major kernelLLVM.clang-unwrapped.version}/include"
          "CFLAGS_KERNEL=-I${final.lib.getLib kernelLLVM.clang-unwrapped}/lib/clang/${final.lib.versions.major kernelLLVM.clang-unwrapped.version}/include"
        ];
        extraMeta.branch = "7.2";
        features.rust = true;
        kernelPatches = [{ name = "apple-m4-wait-state";
          patch = ./kernel/0001-arm64-apple-m4-wait-state.patch; }] ++ _kernelPatches;
      }).overrideAttrs (old: {
        env = old.env // { RUSTC_BOOTSTRAP = "1"; };
        nativeBuildInputs = old.nativeBuildInputs ++ [ final.binutils kernelLLVM.lld ];
        # Refresh compiler capability probes using the same resolved hardware
        # configuration as Fedora. Validate the shared fragments afterwards.
        configurePhase = final.lib.replaceStrings
          [ "ln -sv" " oldconfig" ] [ "cp -v" " olddefconfig" ] old.configurePhase;
        postConfigure = ''
          python3 ${stableFile ./kernel/validate-config.py} ${stableFile ./kernel/common.config} "$buildRoot/.config"
          python3 ${stableFile ./kernel/validate-config.py} ${stableFile ./kernel/neo.config} "$buildRoot/.config"
          grep -qx 'CONFIG_RUST=y' "$buildRoot/.config"
          grep -qx 'CONFIG_ARM64_16K_PAGES=y' "$buildRoot/.config"
          make "''${makeFlags[@]}" rustavailable
          make "''${makeFlags[@]}" certs/
          "$buildRoot/certs/extract-cert" "" "$TMPDIR/aurora-empty-cert"
        '';
      })))) { };
  m1n1 = (prev.m1n1.override { customLogo = null; }).overrideAttrs (old: {
    pname = "aura";
    version = pins.aura.version;
    src = source "aura";
    cargoDeps = final.rustPlatform.importCargoLock {
      lockFile = ./locks/aura.Cargo.lock;
      outputHashes."fatfs-0.4.0" = "sha256-r1STNZupll2U5MppT0gNmEKDl9gevRTYZFOAVimtZxU=";
    };
    postPatch = "";
    makeFlags = [ "RELEASE=1" "CHAINLOADING=1" "BUILTIN_LOGO=aurora" ];
    postBuild = ''
      mkdir -p stage1
      cp build/aura.bin stage1/aura-raw.bin
      cp build/aura.macho stage1/aura.macho
      make clean
      make $makeFlags ESP_STAGE2=1
    '';
    installPhase = ''
      mkdir -p $out/lib/m1n1 $out/share/aura/stage1
      cp build/aura.bin $out/lib/m1n1/m1n1.bin
      cp stage1/* $out/share/aura/stage1/
    '';
    doCheck = false; # Upstream m1n1's Python suite is not the Aura test suite.
  });
  uboot-asahi = prev.uboot-asahi.overrideAttrs (old: {
    src = source "uboot-aurora";
    version = pins.uboot-aurora.version;
    patches = [ ];
  });
  mesa = final.callPackage ./mesa.nix { mesa = prev.mesa; src = source "mesa-aurora"; };
  asahi-audio = prev.asahi-audio.overrideAttrs (old: {
    src = source "aurora-audio";
    version = pins.aurora-audio.version;
  });
  alsa-ucm-conf-asahi = prev.alsa-ucm-conf-asahi.overrideAttrs (old: {
    src = source "alsa-ucm-conf-aurora";
    version = pins.alsa-ucm-conf-aurora.version;
  });
  speakerguardd = rustPackage "speakerguardd" ./locks/speakerguardd.Cargo.lock {
    nativeBuildInputs = [ final.pkg-config ];
    buildInputs = [ final.alsa-lib ];
    postInstall = ''
      mkdir -p $out/share/speakerguardd
      cp -r conf/* $out/share/speakerguardd/
      mkdir -p $out/lib/systemd/system $out/lib/udev/rules.d $out/libexec/speakerguardd
      substitute speakerguardd.service $out/lib/systemd/system/speakerguardd.service \
        --replace-fail "ExecStart=/usr/bin/speakerguardd -c /usr/share/speakerguardd" \
          "ExecStart=$out/bin/speakerguardd -c $out/share/speakerguardd -C AppleJ700" \
        --replace-fail "Description=Speaker Protection Daemon (feed-forward)" \
          $'Description=Speaker Protection Daemon (feed-forward)\nStartLimitIntervalSec=60\nStartLimitBurst=10' \
        --replace-fail $'StartLimitInterval=60\nStartLimitBurst=10\n' ""
      cp 95-speakerguardd.rules $out/lib/udev/rules.d/
      cp ${stableFile ./firmware/use-feedback-guard} $out/libexec/speakerguardd/use-feedback-guard
      chmod +x $out/libexec/speakerguardd/use-feedback-guard
      patchShebangs $out/libexec/speakerguardd/use-feedback-guard
    '';
  };
  bankstown-lv2 = prev.bankstown-lv2.overrideAttrs (old: {
    src = source "bankstown";
    version = pins.bankstown.version;
    cargoDeps = final.rustPlatform.importCargoLock { lockFile = ./locks/bankstown.Cargo.lock; };
  });
  aurora-neo-platform-config = final.stdenvNoCC.mkDerivation {
    pname = "aurora-neo-platform-config";
    version = pins.aurora-neo-platform-config.version;
    src = source "aurora-neo-platform-config";
    dontBuild = true;
    doCheck = true;
    checkPhase = "sh tests/run.sh";
    installFlags = [ "PREFIX=$(out)" ];
  };
  aurora-bless = rustPackage "aurora-bless" ./locks/aurora-bless.Cargo.lock {
    cargoBuildFlags = [ "-p" "asahi-bless" ];
    cargoTestFlags = [ "-p" "asahi-bless" "-p" "apple-nvram" "-p" "asahi-nvram" ];
  };
}
