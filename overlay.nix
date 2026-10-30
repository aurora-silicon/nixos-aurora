final: prev:
let
  stableFile = path: final.writeText (builtins.baseNameOf path) (builtins.readFile path);
  kernelConfig = final.lib.listToAttrs (final.lib.concatMap (line:
    let matched = builtins.match "(CONFIG_[^=]+)=([ym])" line;
    in final.lib.optional (matched != null) {
      name = builtins.elemAt matched 0; value = builtins.elemAt matched 1;
    }) (final.lib.splitString "\n" (builtins.readFile ./kernel/nixos.config)));
  kernelLLVM = final.llvmPackages_22;
  # GNOME Initial Setup creates the owner account on GNOME images (its
  # new-user mode). nixpkgs' vendor file skips the account and password pages,
  # which only that mode shows; keep its other choices.
  gnomeInitialSetupVendor = final.writeText "aurora-gnome-initial-setup-vendor.conf" ''
    [pages]
    skip=software;timezone;
  '';
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
  guestPkgs = system: import final.path { inherit system; };
  x86 = guestPkgs "x86_64-linux";
  x86_32 = guestPkgs "i686-linux";
  mesaCompilerTools = (x86.callPackage ./mesa.nix {
    src = source "mesa-aurora";
    commit = pins.mesa-aurora.commit;
  }).overrideAttrs (old: {
    pname = "aurora-mesa-compiler-tools";
    configurePhase = ''
      runHook preConfigure
      meson setup tools --prefix="$out" --libdir=lib --buildtype=release "''${mesonFlags[@]}" \
        -Dllvm=enabled -Dbuild-tests=false
    '';
    buildPhase = ''
      ninja -C tools -j "$NIX_BUILD_CORES" src/compiler/clc/mesa_clc \
        src/compiler/spirv/vtn_bindgen2 src/asahi/clc/asahi_clc
    '';
    doCheck = false;
    installPhase = ''
      mkdir -p $out/bin
      cp tools/src/compiler/clc/mesa_clc tools/src/compiler/spirv/vtn_bindgen2 \
        tools/src/asahi/clc/asahi_clc $out/bin/
    '';
    postFixup = "";
    disallowedRequisites = [ ];
    allowedReferences = null;
  });
  guestMesa = packages: packages.callPackage ./mesa.nix {
    src = source "mesa-aurora";
    commit = pins.mesa-aurora.commit;
    guest = true;
    compilerTools = mesaCompilerTools;
  };
in {
  kdePackages = prev.kdePackages.overrideScope (_: kdePrev: {
    kinfocenter = kdePrev.kinfocenter.overrideAttrs (old: {
      patches = (old.patches or [ ]) ++ map stableFile [
        ./patches/kinfocenter-unknown-memory.patch
      ];
    });
    powerdevil = kdePrev.powerdevil.overrideAttrs (old: {
      patches = (old.patches or [ ]) ++ map stableFile [
        ./patches/powerdevil-no-empty-keyboard-backlight.patch
      ];
    });
    # NixOS paths: the completion flag in /etc (not the package's etc), and the
    # system profile for the account helper's useradd, usermod and chpasswd.
    plasma-setup = kdePrev.plasma-setup.overrideAttrs (old: {
      patches = (old.patches or [ ]) ++ map stableFile [
        ./patches/plasma-setup-nixos-paths.patch
        # NixOS shows each page package under two data directories; list each page once.
        ./patches/plasma-setup-unique-pages.patch
      ];
    });
  });
  gnome-initial-setup = prev.gnome-initial-setup.overrideAttrs (old: {
    mesonFlags = map (flag: if final.lib.hasPrefix "-Dvendor-conf-file=" flag
      then "-Dvendor-conf-file=${gnomeInitialSetupVendor}" else flag) old.mesonFlags;
  });
  # GDM looks for GNOME Initial Setup's session in its own store path. Only the
  # display manager's daemon uses this build (modules/gnome-initial-setup.nix),
  # so gnome-shell, which links GDM's library, is not rebuilt.
  aurora-gdm = prev.gdm.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ map stableFile [
      ./patches/gdm-initial-setup-session-path.patch
    ];
  });
  aurora-sep = final.callPackage ./sep/package.nix { };
  libfprint = prev.libfprint.overrideAttrs (old: {
    src = source "libfprint";
    version = pins.libfprint.version;
    nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ final.umockdev ];
    nativeInstallCheckInputs = [ final.umockdev (final.python3.withPackages (p: [ p.pygobject3 p.pycairo ])) ];
    patches = (old.patches or [ ]) ++ map stableFile [
      ./sep/libfprint-1.94.100-apple-sep.patch
      ./sep/0002-aurora-report-unusable-captures-as-retries.patch
      ./sep/0003-hide-lid-covered-readers-while-the-lid-is-closed.patch
    ];
    postPatch = (old.postPatch or "") + ''
      install -Dm644 ${stableFile ./sep/apple-sep.h} aurora-uapi/linux/apple-sep.h
    '';
    preConfigure = (old.preConfigure or "") + ''
      export CFLAGS="''${CFLAGS:-} -I$PWD/aurora-uapi"
    '';
  });
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
        version = "7.3.0";
        modDirVersion = "7.3.0";
        src = source "kernel-aurora";
        configfile = stableFile ./kernel/nixos.config;
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
        extraMeta.branch = "7.3";
        features.rust = true;
        kernelPatches = _kernelPatches;
      }).overrideAttrs (finalAttrs: old: {
        # NixOS consumers (including ASLR limits) need the resolved config,
        # which the kernel builder already installs in its development output.
        # Keep the configure input fragment private to the build environment.
        passthru = old.passthru // {
          configfile = "${finalAttrs.finalPackage.dev}/lib/modules/${old.passthru.modDirVersion}/build/.config";
        };
        env = old.env // { RUSTC_BOOTSTRAP = "1"; };
        nativeBuildInputs = old.nativeBuildInputs ++ [ final.binutils kernelLLVM.lld ];
        # The source-tree entry point is selected by the pinned Kbuild.
        postPatch = (old.postPatch or "") + ''
          mkdir -p tools/aurora-bindgen/build/bin
          ln -s ${final.aurora-bindgen}/bin/bindgen tools/aurora-bindgen/build/bin/bindgen
        '';
        # Always derive the universal configuration from this source's
        # defconfig and hardware defaults, rather than a stale resolved base.
        configurePhase = ''
          runHook preConfigure
          mkdir build
          export buildRoot="$PWD/build"
          make "''${makeFlags[@]}" defconfig
          bash scripts/kconfig/merge_config.sh -m -O "$buildRoot" \
            "$buildRoot/.config" arch/arm64/configs/asahi.config \
            ${stableFile ./kernel/common.config} ${stableFile ./kernel/nixos.config}
          make "''${makeFlags[@]}" olddefconfig
          runHook postConfigure
          make "''${makeFlags[@]}" prepare
          test "$(cat "$buildRoot/include/config/kernel.release")" = 7.3.0
          buildFlags+=("KBUILD_BUILD_TIMESTAMP=$(date -u -d @$SOURCE_DATE_EPOCH)")
          cd "$buildRoot"
        '';
        postConfigure = ''
          python3 ${stableFile ./kernel/validate-config.py} arch/arm64/configs/asahi.config \
            ${stableFile ./kernel/common.config} ${stableFile ./kernel/nixos.config} "$buildRoot/.config"
          grep -qx 'CONFIG_RUST=y' "$buildRoot/.config"
          grep -qx 'CONFIG_ARM64_16K_PAGES=y' "$buildRoot/.config"
          make "''${makeFlags[@]}" rustavailable
          make "''${makeFlags[@]}" certs/
          "$buildRoot/certs/extract-cert" "" "$TMPDIR/aurora-empty-cert"
        '';
        postInstall = (old.postInstall or "") + ''
          echo ${pins.kernel-aurora.commit} > "$out/aurora-source-commit"
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
    # Build with clang and lld, as Fedora and Arch do. With GCC, aura's image
    # outgrows the space that aura-raw.ld leaves before the DCP log buffer.
    # python3 runs the build's built-in logo check.
    nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [
      kernelLLVM.clang-unwrapped kernelLLVM.lld kernelLLVM.llvm final.buildPackages.python3
    ];
    makeFlags = [ "RELEASE=1" "CHAINLOADING=1" "BUILTIN_LOGO=aurora" "USE_CLANG=1" ];
    # This pin is the v1.0.0b1 tag, so the build carries that release label
    # instead of 1.0.0b1-g<commit>. track-sources.py drops it when aura moves on.
    env = (old.env or { }) // { AURA_VERSION_TAG = "1.0.0b1"; };
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
  mesa = final.callPackage ./mesa.nix {
    mesa = prev.mesa;
    src = source "mesa-aurora";
    commit = pins.mesa-aurora.commit;
  };
  aurora-fex-mesa = x86.runCommand "aurora-fex-mesa-${pins.mesa-aurora.version}-${builtins.substring 0 12 pins.mesa-aurora.commit}" {
    nativeBuildInputs = [ x86.binutils ];
    passthru = { inherit (pins.mesa-aurora) commit; };
  } ''
    mkdir -p $out/usr
    cp -a ${guestMesa x86}/usr/lib64 $out/usr/
    cp -a ${guestMesa x86_32}/usr/lib $out/usr/
    cp -a ${guestMesa x86}/usr/share $out/usr/
    # The manifest directory is shared by both guest architectures.
    chmod -R u+w $out/usr/share
    cp -a --update=none ${guestMesa x86_32}/usr/share/. $out/usr/share/
    echo ${pins.mesa-aurora.commit} > $out/.aurora-mesa-commit
    for library in $out/usr/lib64/libgallium*.so $out/usr/lib64/libvulkan_asahi.so; do
      readelf -h "$library" | grep -q 'Advanced Micro Devices X86-64'
      readelf -n "$library" | grep -Eq 'Build ID: [0-9a-f]{40}'
    done
    for library in $out/usr/lib/libgallium*.so $out/usr/lib/libvulkan_asahi.so; do
      readelf -h "$library" | grep -q 'Intel 80386'
      readelf -n "$library" | grep -Eq 'Build ID: [0-9a-f]{40}'
    done
  '';
  aurora-flatpak-gl = final.callPackage ./flatpak-gl/package.nix {
    mesaSrc = source "mesa-aurora";
    mesaPin = pins.mesa-aurora;
  };
  aurora-alsa-utils = (final.callPackage (final.path + "/pkgs/by-name/al/alsa-utils/package.nix") { }).overrideAttrs (old: {
    src = source "alsa-utils";
    version = pins.alsa-utils.version;
    patches = (old.patches or [ ]) ++ map stableFile [
      ./patches/alsactl-skip-locked-controls.patch
    ];
  });
  asahi-audio = prev.asahi-audio.overrideAttrs (old: {
    src = source "aurora-audio";
    version = pins.aurora-audio.version;
    postInstall = (old.postInstall or "") + ''
      echo ${pins.aurora-audio.commit} > "$out/.aurora-audio-commit"
    '';
  });
  # A VRR-capable output defaults to variable refresh rate: the variable
  # variant of the preferred mode becomes the preferred one, which new monitor
  # configurations use. Saved configurations still win. The same patch is in
  # fedora-aurora's mutter package (fedora-aurora PR 41).
  mutter = prev.mutter.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ map stableFile [
      ./patches/mutter-prefer-variable-refresh-rate.patch
    ];
  });
  # nixpkgs exposes a symlink join here: overriding its src does not replace
  # the inner model derivation. Build the pinned models explicitly, then merge
  # them ahead of the native common UCM definitions.
  alsa-ucm-conf-asahi = let
    models = final.stdenvNoCC.mkDerivation {
      pname = "aurora-ucm-models";
      version = pins.alsa-ucm-conf-aurora.version;
      src = source "alsa-ucm-conf-aurora";
      dontBuild = true;
      installPhase = ''
        runHook preInstall
        mkdir -p "$out/share/alsa"
        cp -r ucm2 "$out/share/alsa/"
        echo ${pins.alsa-ucm-conf-aurora.commit} > "$out/.aurora-ucm-commit"
        runHook postInstall
      '';
    };
  in final.symlinkJoin {
    pname = "alsa-ucm-conf-aurora";
    inherit (models) version src;
    paths = [ models final.alsa-ucm-conf ];
    postBuild = ''
      test "$(cat "$out/.aurora-ucm-commit")" = ${pins.alsa-ucm-conf-aurora.commit}
      grep -qF 'JackControl "Internal Mic Jack"' \
        "$out/share/alsa/ucm2/conf.d/aop_audio/3chan/HiFi.conf"
      test -f "$out/share/alsa/ucm2/conf.d/macaudio/MacBook Neo J700.conf"
    '';
    passthru.commit = pins.alsa-ucm-conf-aurora.commit;
    meta = {
      description = "Aurora model profiles with native common ALSA UCM definitions";
      homepage = "https://github.com/aurora-silicon/alsa-ucm-conf-asahi";
      license = final.lib.licenses.bsd3;
      platforms = [ "aarch64-linux" ];
    };
  };
  # Fedora Aurora's speakersafetyd-aurora-profiles: the J616s speaker model
  # (speakersafetyd's J316 values with the J616 V/I sense layout) and the udev
  # rule that starts the daemon for its card. The daemon reads its models from
  # its own share directory, so they go into the package.
  speakersafetyd = prev.speakersafetyd.overrideAttrs (old: {
    postInstall = (old.postInstall or "") + ''
      install -Dm644 ${stableFile ./speakersafetyd/j616.conf} $out/share/speakersafetyd/apple/j616.conf
      install -Dm644 ${stableFile ./speakersafetyd/96-speakersafetyd-aurora.rules} \
        $out/lib/udev/rules.d/96-speakersafetyd-aurora.rules
    '';
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
