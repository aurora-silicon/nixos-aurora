final: prev:
let
  stableFile = path: final.writeText (builtins.baseNameOf path) (builtins.readFile path);
  # nixpkgs constructs the CLI and engine with the same builder argument.
  # Patch only the engine, so the resulting Docker symlinks and wrappers all
  # refer to the fixed moby derivation, including its exposed .moby output.
  dockerPolicyBuilder = args: prev.buildGoModule (args // final.lib.optionalAttrs
    ((args.pname or "") == "moby") {
      patches = (args.patches or [ ]) ++ [ (stableFile ./patches/docker-query-forwarding-policy.patch) ];
      doCheck = true;
      checkPhase = ''
        runHook preCheck
        go test -mod=vendor -p=8 ./daemon/libnetwork/iptables -run '^TestSetupDockerForwardingPolicy$' -count=1 -v
        runHook postCheck
      '';
    });
  kernelProvenance = builtins.fromJSON (builtins.readFile ./kernel/provenance.json);
  kernelBase =
    assert final.lib.assertMsg
      (kernelProvenance.kernel_commit == pins."kernel-aurora".commit
        && kernelProvenance.config_upstream.kernel_commit == kernelProvenance.kernel_commit)
      "Refresh the canonical ALARM resolved config together with the kernel pin";
    assert final.lib.assertMsg
      (builtins.hashFile "sha256" ./kernel/config == kernelProvenance.config_upstream.config_sha256)
      "The vendored ALARM resolved config does not match its provenance";
    builtins.readFile ./kernel/config;
  kernelBaseFile = final.writeText "config" kernelBase;
  # The shared distribution config with NixOS's requirements on top, as the
  # build merges them. NixOS modules read kernel features from this.
  kernelConfig = final.lib.listToAttrs (final.lib.concatMap (line:
    let matched = builtins.match "(CONFIG_[^=]+)=([ym])" line;
    in final.lib.optional (matched != null) {
      name = builtins.elemAt matched 0; value = builtins.elemAt matched 1;
    }) (final.lib.splitString "\n" (kernelBase + "\n" + builtins.readFile ./kernel/nixos.config)));
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
    outputs = [ "out" ];
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
  libvaV4l2RequestAvd = final.callPackage ./libva-v4l2-request-avd.nix {
    src = source "libva-v4l2-request-avd";
    version = pins.libva-v4l2-request-avd.version;
    portabilityPatch = stableFile ./patches/libva-v4l2-request-offline-test-portability.patch;
  };
  plymouth = prev.plymouth.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ [
      (stableFile ./plymouth/0001-ply-terminal-Keep-terminal-input-nonblocking.patch)
      (stableFile ./plymouth/0001-systemd-units-Start-plymouthd-without-waiting-for-coldplug.patch)
      # Clear the previous DRM master's HDR state before the SDR splash scans out.
      (stableFile ./plymouth/0002-drm-Reset-inherited-HDR-connector-state-before-SDR.patch)
    ];
    doCheck = true;
    postCheck = (old.postCheck or "") + ''
      # Meson runs checks from the build directory; headers live in the source.
      $CC -D_GNU_SOURCE -Wall -Wextra -Werror \
        -I. -I.. -I../src/libply -I../src/libply-splash-core \
        ${stableFile ./plymouth/test-terminal-input.c} -o test-terminal-input \
        -Lsrc/libply-splash-core -Lsrc/libply \
        -Wl,-rpath,"$PWD/src/libply-splash-core" \
        -Wl,-rpath,"$PWD/src/libply" \
        -lply-splash-core -lply
      timeout 15s ./test-terminal-input
      echo 'Plymouth terminal-input PTY regression passed'
      # The DRM regression includes the production renderer and mocks libdrm.
      $CC -D_GNU_SOURCE -Wall \
        -I. -I.. -I../src/libply -I../src/libply-splash-core \
        $($PKG_CONFIG --cflags libdrm libevdev) \
        ${stableFile ./plymouth/test-drm-sdr.c} -o test-drm-sdr \
        -Lsrc/libply-splash-core -Lsrc/libply \
        -Wl,-rpath,"$PWD/src/libply-splash-core" \
        -Wl,-rpath,"$PWD/src/libply" \
        -lply-splash-core -lply $($PKG_CONFIG --libs libdrm libevdev) -lm
      timeout 15s ./test-drm-sdr
    '';
  });
  docker_29 = prev.docker_29.override { buildGoModule = dockerPolicyBuilder; };
  docker = final.docker_29;
  aurora-logos = final.callPackage ./logos/package.nix { };
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
    nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ final.umockdev final.python3 ];
    nativeInstallCheckInputs = [ final.umockdev (final.python3.withPackages (p: [ p.pygobject3 p.pycairo ])) ];
    patches = (old.patches or [ ]) ++ map stableFile [
      ./sep/libfprint-1.94.100-apple-sep.patch
      ./sep/0002-aurora-report-unusable-captures-as-retries.patch
      ./sep/0003-hide-lid-covered-readers-while-the-lid-is-closed.patch
      ./sep/0004-aurora-refuse-unbound-enrollment.patch
      ./sep/0005-aurora-support-v4-and-v5.patch
      ./sep/0006-aurora-report-finger-lift-and-lockout.patch
    ];
    postPatch = (old.postPatch or "") + ''
      install -Dm644 ${stableFile ./sep/apple-sep.h} aurora-uapi/linux/apple-sep.h
      ${final.python3.interpreter} ${stableFile ./sep/test_interface.py} libfprint/drivers/aurora/aurora.c aurora-uapi/linux/apple-sep.h
    '';
    preConfigure = (old.preConfigure or "") + ''
      export CFLAGS="''${CFLAGS:-} -I$PWD/aurora-uapi"
    '';
  });
  fprintd = prev.fprintd.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ map stableFile [
      ./sep/0001-preserve-print-on-device-delete-failure.patch
    ];
    postPatch = (old.postPatch or "") + ''
      ${final.python3.interpreter} ${stableFile ./sep/test_account_gate.py} src/device.c
    '';
  });
  aurora-firstboot = final.callPackage ./firstboot.nix { };
  aurora-avd-firmware = final.callPackage ./avd-fw.nix {
    src = source "avd-fw";
    version = pins.avd-fw.version;
  };
  # Userspace for the kernel's ANE driver; no firmware, module or overlays.
  mil-hwx-compiler = final.callPackage ./mil-hwx-compiler.nix {
    basePatch = stableFile ./ane/gnustep-base-block-ivar.patch;
    baseSrc = let pin = pins.mil-hwx-compiler.extra_sources.gnustep-base; in final.fetchurl {
      name = "gnustep-base-${pin.commit}.tar.gz";
      url = pin.source_url;
      sha256 = pin.sha256;
    };
    src = source "mil-hwx-compiler";
    version = pins.mil-hwx-compiler.version;
  };
  omarchy-ane-tools = final.callPackage ./omarchy-ane-tools.nix {
    src = source "omarchy-ane-tools";
    version = pins.omarchy-ane-tools.version;
  };
  # Drive.Size for NVMe controllers that leave TNVMCAP at zero, such as the
  # Apple silicon SSDs, from their namespaces (udisks f032f09cc760 for 2.11.x),
  # so GNOME's About page and desktop tools show the internal disk's capacity.
  udisks = prev.udisks.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ [ (stableFile ./patches/udisks-nvme-namespace-size.patch) ];
  });
  # PipeWire with the patches fedora-aurora and alarm-aurora carry, for the
  # daemon (modules/audio.nix sets it as services.pipewire.package). It is a
  # separate attribute, not a replacement for pipewire: clients that link
  # libpipewire (SDL, Qt, the portals, the compositors) keep nixpkgs' cached
  # builds, and the fixed code runs where the speaker graph runs, in the
  # daemon's filter-chain. 1006: filter-graph keeps the software volume at
  # unity on every volume or mute update, so a repeated write no longer
  # applies the speaker volume twice (-31 dB at a 30 % slider). 1005: it
  # follows its plugins' latency after activation. 1007: spa-alsa waits a
  # period after a refused start and reports refusals at most once per 5 s. 1000-1004: AirPlay (RAOP)
  # sender fixes. nixpkgs runs the meson suite, with both new tests.
  aurora-pipewire = prev.pipewire.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ map stableFile [
      ./patches/pipewire/1000-module-raop-match-an-RTSP-reply-without-CSeq-to-the-.patch
      ./patches/pipewire/1001-module-raop-sink-say-why-a-receiver-session-was-drop.patch
      ./patches/pipewire/1002-module-raop-sink-default-sess.latency.msec-to-whole-.patch
      ./patches/pipewire/1003-module-raop-discover-reload-a-sink-that-unloaded-its.patch
      ./patches/pipewire/1004-module-raop-sink-give-up-on-a-session-that-never-rea.patch
      ./patches/pipewire/1005-filter-graph-follow-plugin-latency-after-activation.patch
      ./patches/pipewire/1006-filter-graph-keep-the-software-volume-at-unity-on-ev.patch
      ./patches/pipewire/1007-alsa-back-off-a-refused-snd_pcm_start-and-rate-limit.patch
    ];
    doCheck = true;
  });
  upower = prev.upower.overrideAttrs (old: {
    src = source "upower-aurora";
    version = pins.upower-aurora.version;
    doCheck = true;
    postConfigure = (old.postConfigure or "") + ''
      meson test --list > aurora-registered-tests.txt
      grep -q test_macsmc_kernel_time_at_zero_rate aurora-registered-tests.txt
      grep -q test_other_supply_ignores_kernel_time aurora-registered-tests.txt
      grep -q test_macsmc_kernel_time_charge_units aurora-registered-tests.txt
    '';
  });
  # FEX from Aurora's fork in place of nixpkgs' (fex.nix).
  fex = final.callPackage ./fex.nix { fex = prev.fex; pin = pins.fex-emu; };
  # Aurora's Steam: nixpkgs' steam FHS environment around the native ARM64
  # launcher (steam/package.nix) in place of Valve's x86 bootstrap.
  steam-unwrapped = final.callPackage ./steam/package.nix {
    src = source "aurora-steam-native";
    inherit (pins.aurora-steam-native) commit;
  };
  steam = final.callPackage ./steam/fhs.nix { };
  # The userpages launcher, from the kernel's own source: it uses that tree's
  # private PR_AURORA_* prctl numbers.
  aurora-userpages = final.stdenv.mkDerivation {
    pname = "aurora-userpages";
    version = pins.kernel-aurora.version;
    src = source "kernel-aurora";
    # Only the launcher, its prctl header and the license.
    unpackPhase = ''
      runHook preUnpack
      root=${pins.kernel-aurora.archive_root}
      tar -xzf "$src" "$root/COPYING" "$root/include/uapi/linux/prctl.h" "$root/tools/aurora-userpages"
      sourceRoot=$root
      runHook postUnpack
    '';
    buildPhase = ''
      runHook preBuild
      make -C tools/aurora-userpages
      runHook postBuild
    '';
    installPhase = ''
      runHook preInstall
      install -Dm755 tools/aurora-userpages/userpages "$out/bin/userpages"
      install -Dm644 tools/aurora-userpages/README.rst "$out/share/doc/aurora-userpages/README.rst"
      install -Dm644 COPYING "$out/share/licenses/aurora-userpages/COPYING"
      runHook postInstall
    '';
    doInstallCheck = true;
    installCheckPhase = ''
      "$out/bin/userpages" --help | grep -q '{native|4k|16k|64k} COMMAND'
    '';
    passthru = { inherit (pins.kernel-aurora) commit; };
    meta = {
      description = "Run programs with 4K userspace pages on the Aurora kernel";
      license = final.lib.licenses.gpl2Only;
      mainProgram = "userpages";
      platforms = [ "aarch64-linux" ];
    };
  };
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
        configfile = kernelBaseFile;
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
        # Start from the resolved configuration alarm-aurora ships for this
        # kernel (kernel/config, see kernel/provenance.json), so every
        # distribution builds the same options, and add only NixOS's own
        # requirements on top.
        configurePhase = ''
          runHook preConfigure
          # nixpkgs installs this tree beside source/ in the dev output.
          # Keep it outside source/ so its postInstall move cannot target itself.
          export buildRoot="$NIX_BUILD_TOP/build"
          mkdir -- "$buildRoot"
          cp ${kernelBaseFile} "$buildRoot/.config"
          chmod u+w "$buildRoot/.config"
          bash scripts/kconfig/merge_config.sh -m -O "$buildRoot" \
            "$buildRoot/.config" ${stableFile ./kernel/nixos.config}
          make "''${makeFlags[@]}" olddefconfig
          runHook postConfigure
          make "''${makeFlags[@]}" prepare
          test "$(cat "$buildRoot/include/config/kernel.release")" = 7.3.0
          buildFlags+=("KBUILD_BUILD_TIMESTAMP=$(date -u -d @$SOURCE_DATE_EPOCH)")
        '';
        postConfigure = ''
          python3 ${stableFile ./kernel/validate-config.py} arch/arm64/configs/asahi.config \
            ${stableFile ./kernel/nixos.config} "$buildRoot/.config"
          python3 ${stableFile ./kernel/check-required.py} "$buildRoot/.config"
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
    # This pin carries the v1.0.0b5 release label in archive builds.
    env = (old.env or { }) // { AURA_VERSION_TAG = "1.0.0b5"; };
    postBuild = ''
      mkdir -p stage1
      cp build/aura.bin stage1/aura-raw.bin
      cp build/aura.macho stage1/aura.macho
      cp build/aura-boot.macho stage1/aura-boot.macho
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
  mesa = (final.callPackage ./mesa.nix {
    mesa = prev.mesa;
    src = source "mesa-aurora";
    commit = pins.mesa-aurora.commit;
  }).overrideAttrs (old: {
    # Preserve the conventional interface without retaining LLVM in GL's closure.
    passthru = old.passthru // { opencl = final.aurora-rusticl; };
  });
  aurora-lavapipe = final.callPackage ./lavapipe.nix {
    mesa = prev.mesa;
    src = source "mesa-aurora";
    commit = pins.mesa-aurora.commit;
  };
  aurora-rusticl = final.callPackage ./rusticl.nix {
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
    version = "${pins.aurora-audio.version}-aurora8";
    postInstall = (old.postInstall or "") + ''
      echo ${pins.aurora-audio.commit} > "$out/.aurora-audio-commit"
    '';
  });
  # A VRR-capable output defaults to variable refresh rate: the variable
  # variant of the preferred mode becomes the preferred one, which new monitor
  # configurations use. Saved configurations still win. The same patch is in
  # fedora-aurora's mutter package (fedora-aurora PR 41).
  # A panel that scales PQ with its backlight reports PQ_REFERENCE_LUMINANCE;
  # in BT.2100 mode mutter then keeps that backlight as the brightness control
  # and puts its reference white at the reported PQ level (PQ 100 cd/m² on
  # Apple's EDR panels) instead of 203 cd/m².
  # A built-in panel in a variable refresh rate mode uses it on its whole
  # desktop, not only for fullscreen surfaces, so an idle desktop lets the
  # panel drop to its minimum rate.
  mutter = prev.mutter.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ map stableFile [
      ./patches/mutter-prefer-variable-refresh-rate.patch
      ./patches/mutter-pq-reference-luminance.patch
      ./patches/mutter-builtin-desktop-vrr.patch
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
    # The binary names its source in -V and the journal. The unit keeps its
    # own start limit (five attempts in 60 s); only the J700 model is named.
    env.SPEAKERGUARDD_COMMIT = builtins.substring 0 12 pins.speakerguardd.commit;
    nativeBuildInputs = [ final.pkg-config ];
    buildInputs = [ final.alsa-lib ];
    postInstall = ''
      mkdir -p $out/share/speakerguardd
      cp -r conf/* $out/share/speakerguardd/
      mkdir -p $out/lib/systemd/system $out/lib/udev/rules.d $out/libexec/speakerguardd
      substitute speakerguardd.service $out/lib/systemd/system/speakerguardd.service \
        --replace-fail "ExecStart=/usr/bin/speakerguardd -c /usr/share/speakerguardd --wait-for-card 30" \
          "ExecStart=$out/bin/speakerguardd -c $out/share/speakerguardd -C AppleJ700 --wait-for-card 30"
      cp 95-speakerguardd.rules $out/lib/udev/rules.d/
      cp ${stableFile ./firmware/use-feedback-guard} $out/libexec/speakerguardd/use-feedback-guard
      chmod +x $out/libexec/speakerguardd/use-feedback-guard
      patchShebangs $out/libexec/speakerguardd/use-feedback-guard
    '';
  };
  # speakerguardd 1.0 (the v2 branch): a new program, packaged beside the 0.1
  # daemon above. modules/speakerguardd-v2.nix installs it and holds the
  # opt-in that makes it the speaker protection (aurora.speakerguardd.v2).
  speakerguardd-v2 = let
    # The crates this package ships; the rig and benchmark crates stay out.
    crates = [ "-p" "sgv2-core" "-p" "sgv2-lv2" "-p" "sgv2-supervisor" "-p" "aurora-speaker-tuning" ];
    units = [ "speakerguardd.service" "speakerguardd-provision.service" "speakerguardd-selfcheck.service"
              "speakerguardd-seat.service" "speakerguardd-seat.path" "speakerguardd-sleep.service" ];
    userUnits = [ "speakerguardd-session.service" "speakerguardd-graph.service" ];
  in rustPackage "speakerguardd-v2" ./locks/speakerguardd-v2.Cargo.lock {
    cargoBuildFlags = crates;
    cargoTestFlags = crates;
    # Provisioning, the gate, the self-check and the session helper are
    # Python; their shebangs are patched to this interpreter. The tools they
    # call come from the units' path (modules/speakerguardd-v2.nix), except
    # the gate's, which also runs as the older daemons' ExecCondition.
    buildInputs = [ final.python3 ];
    nativeCheckInputs = [ final.python3 ];
    postCheck = "python3 -I packaging/session/test_provision.py";
    postInstall = ''
      lx=$out/libexec/speakerguardd-v2
      mkdir -p $lx $out/lib/lv2/sgv2.lv2 $out/lib/systemd/system $out/lib/systemd/user
      mv $out/bin/speakerguardd $lx/speakerguardd
      mv $out/lib/libsgv2_lv2.so $out/lib/lv2/sgv2.lv2/libsgv2_lv2.so
      rm -f $out/lib/*.rlib $out/lib/*.a
      cp crates/sgv2-lv2/lv2/sgv2.lv2/*.ttl $out/lib/lv2/sgv2.lv2/
      # Every plugin the bundle names must be the library installed beside it.
      if grep -ho 'lv2:binary <[^>]*>' $out/lib/lv2/sgv2.lv2/*.ttl | grep -v '<libsgv2_lv2.so>'; then
        echo 'The sgv2 bundle names a library this package does not install' >&2; exit 1
      fi
      for f in speakerguardd-provision speakerguardd-gate speakerguardd-selfcheck speakerguardd-session; do
        install -Dm755 packaging/session/$f $lx/$f
        substituteInPlace $lx/$f --replace-quiet /usr/share/speakerguardd/ $out/share/speakerguardd/
      done
      install -Dm644 packaging/session/wiring.py packaging/session/gen.py -t $lx
      substituteInPlace $lx/speakerguardd-gate $lx/speakerguardd-provision \
        --replace-fail 'default="aurora-speaker-tuning"' "default=\"$out/bin/aurora-speaker-tuning\""
      substituteInPlace $lx/speakerguardd-gate --replace-fail '["amixer",' '["${final.alsa-utils}/bin/amixer",'
      patchShebangs --host $lx
      # The fleet gate's data (qualified boards per protection unit), unchanged
      # from upstream. Every per-board value is derived from the Mac's device
      # tree and tuning at run time (wiring.py); no machine table is shipped.
      install -Dm644 packaging/session/gate.json -t $out/share/speakerguardd
      # The per-machine graphs, as reference data: provisioning generates the
      # machine's own from the self-check's record.
      install -Dm644 packaging/pipewire/sgv2-*.conf -t $out/share/speakerguardd/pipewire
      install -Dm644 packaging/wireplumber/60-sgv2-*.conf -t $out/share/speakerguardd/wireplumber
      install -Dm644 packaging/etc/speakerguardd.conf.example docs/NEW-PLATFORM.md -t $out/share/doc/speakerguardd-v2
      # The upstream units, under their own names so they install beside the
      # 0.1 unit, with the programs where this package installs them.
      rename() {
        sed -e "s@/usr/libexec/speakerguardd/@$lx/@g" -e "s@^ExecStart=/usr/bin/speakerguardd @ExecStart=$lx/speakerguardd @" \
            -e "s@/usr/share/speakerguardd/@$out/share/speakerguardd/@g" \
            -e 's@\bspeakerguardd\(-[a-z]\+\)\?\.\(service\|path\)\b@speakerguardd-v2\1.\2@g' "$1" > "$2"
      }
      for u in ${toString units}; do rename packaging/systemd/$u $out/lib/systemd/system/''${u/speakerguardd/speakerguardd-v2}; done
      for u in ${toString userUnits}; do rename packaging/systemd/$u $out/lib/systemd/user/''${u/speakerguardd/speakerguardd-v2}; done
      sd=$out/lib/systemd/system
      grep -qx "ExecStart=$lx/speakerguardd \$SGV2_ARGS" $sd/speakerguardd-v2.service
      grep -qx 'Requires=speakerguardd-v2-provision.service speakerguardd-v2-selfcheck.service' $sd/speakerguardd-v2.service
      grep -qx 'Requires=speakerguardd-v2-provision.service' $sd/speakerguardd-v2-selfcheck.service
      grep -qx "ExecStart=$lx/speakerguardd-provision seat --unit speakerguardd-v2.service" $sd/speakerguardd-v2-seat.service
      grep -qx "ExecStartPost=$lx/speakerguardd-provision activate --graph-unit speakerguardd-v2-graph.service" $sd/speakerguardd-v2-selfcheck.service
      grep -qx "ExecStart=$lx/speakerguardd-provision sleep --unit speakerguardd-v2.service" $sd/speakerguardd-v2-sleep.service
      grep -qx "ExecStop=$lx/speakerguardd-provision wake --unit speakerguardd-v2.service" $sd/speakerguardd-v2-sleep.service
      for u in speakerguardd-v2 speakerguardd-v2-provision speakerguardd-v2-selfcheck speakerguardd-v2-seat speakerguardd-v2-sleep; do
        grep -qx "ExecCondition=$lx/speakerguardd-gate v2" $sd/$u.service
      done
      if grep -Eq '^(OnFailure|OnSuccess)=|speakersafetyd|=speakerguardd\.service|/usr/' \
          $sd/speakerguardd-v2* $out/lib/systemd/user/speakerguardd-v2*; then
        echo 'A speakerguardd 1.0 unit chains to or names another daemon, or names a /usr path' >&2; exit 1
      fi
      install -Dm644 -t $out/share/licenses/speakerguardd-v2 LICENSE crates/aurora-speaker-tuning/LICENSE-aurora-audio-dsp
    '';
    meta = {
      description = "In-graph speaker protection for Apple Silicon Macs (speakerguardd 1.0, preview)";
      homepage = "https://github.com/aurora-silicon/speakerguardd/tree/v2";
      # aurora-speaker-tuning is based on aurora-audio-dsp by saku, also MIT.
      license = final.lib.licenses.mit;
      platforms = [ "aarch64-linux" ];
      mainProgram = "aurora-speaker-tuning";
    };
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
  # The camera denoise filter, a PipeWire user daemon. Backends load from the
  # package's own lib/aurora-camera-denoise, so a Neural Engine backend has to
  # be built into this derivation. Settings come from /etc, which
  # modules/camera-denoise.nix writes.
  aurora-camera-denoise = final.stdenv.mkDerivation {
    pname = "aurora-camera-denoise";
    version = pins.camera-denoise.version;
    src = source "camera-denoise";
    nativeBuildInputs = [ final.meson final.ninja final.pkg-config ];
    buildInputs = [ final.pipewire ];
    mesonFlags = [
      "-Ddaemon=enabled"
      "-Dsysconfdir=/etc"
      "-Dsystemduserunitdir=${placeholder "out"}/lib/systemd/user"
    ];
    doCheck = true;
    postInstall = ''
      substituteInPlace $out/lib/systemd/user/aurora-camera-denoise.service \
        --replace-fail "ExecReload=/bin/kill" "ExecReload=${final.coreutils}/bin/kill"
    '';
    passthru.commit = pins.camera-denoise.commit;
    meta = {
      description = "PipeWire filter that denoises the built-in camera in low light";
      homepage = "https://github.com/aurora-silicon/camera-denoise";
      license = final.lib.licenses.mit;
      mainProgram = "aurora-camera-denoise";
      platforms = [ "aarch64-linux" ];
    };
  };
  # The keyboard backlight that follows the ambient light sensor, a system
  # service. modules/kbd-light.nix enables it and writes its settings.
  aurora-kbd-light = final.stdenv.mkDerivation {
    pname = "aurora-kbd-light";
    version = pins.kbd-light.version;
    src = source "kbd-light";
    makeFlags = [ "PREFIX=${placeholder "out"}" "UNITDIR=${placeholder "out"}/lib/systemd/system" ];
    postInstall = ''
      substituteInPlace $out/lib/systemd/system/aurora-kbd-light.service \
        --replace-fail "ExecStart=/usr/bin/aurora-kbd-light" "ExecStart=$out/bin/aurora-kbd-light"
    '';
    passthru.commit = pins.kbd-light.commit;
    meta = {
      description = "Keyboard backlight that follows the ambient light sensor";
      homepage = "https://github.com/aurora-silicon/kbd-light";
      license = final.lib.licenses.mit;
      mainProgram = "aurora-kbd-light";
      platforms = [ "aarch64-linux" ];
    };
  };
  aurora-bless = rustPackage "aurora-bless" ./locks/aurora-bless.Cargo.lock {
    cargoBuildFlags = [ "-p" "asahi-bless" ];
    cargoTestFlags = [ "-p" "asahi-bless" "-p" "apple-nvram" "-p" "asahi-nvram" ];
  };
}
