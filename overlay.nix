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
  mesaCompilerTools = x86.callPackage ./pkgs/mesa-compiler-tools.nix {
    src = source "mesa-aurora";
    inherit (pins.mesa-aurora) version commit;
  };
  guestMesa = packages: packages.callPackage ./mesa.nix {
    src = source "mesa-aurora";
    inherit (pins.mesa-aurora) version commit;
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
      inherit (pin) sha256;
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
  fex = import ./fex.nix {
    inherit (final) lib fetchurl runCommand;
    inherit (prev) fex;
    pin = pins.fex-emu;
  };
  aurora-proton = final.callPackage ./pkgs/proton { };
  # Aurora's Steam: nixpkgs' steam FHS environment around the native ARM64
  # launcher (steam/package.nix) in place of Valve's x86 bootstrap.
  steam-unwrapped = final.callPackage ./steam/package.nix {
    src = source "aurora-steam-native";
    inherit (pins.aurora-steam-native) commit;
  };
  steam = final.callPackage ./steam/fhs.nix { };
  # The userpages launcher, from the kernel's own source: it uses that tree's
  # private PR_AURORA_* prctl numbers.
  aurora-userpages = final.callPackage ./pkgs/userpages.nix {
    src = source "kernel-aurora";
    pin = pins.kernel-aurora;
  };
  aurora-bindgen = final.callPackage ./bindgen { llvmPackages = kernelLLVM; };
  linux-asahi = final.lib.makeOverridable ({ _kernelPatches ? [ ] }:
    final.lib.recurseIntoAttrs (final.linuxPackagesFor (import ./pkgs/kernel.nix {
      # Preserve buildLinux's .override API (features, extraMakeFlags, ...).
      inherit (final) lib callPackage path writeText openssl binutils aurora-bindgen;
      src = source "kernel-aurora";
      pin = pins.kernel-aurora;
      llvmPackages = kernelLLVM;
      kernelPatches = _kernelPatches;
    }))) { };
  # Keep m1n1.override { customLogo = ...; } available to installed systems.
  m1n1 = import ./pkgs/aura.nix {
    inherit (final) lib rustPlatform buildPackages;
    inherit (prev) m1n1;
    src = source "aura";
    pin = pins.aura;
    llvmPackages = kernelLLVM;
  };
  uboot-asahi = prev.uboot-asahi.overrideAttrs (_old: {
    src = source "uboot-aurora";
    version = pins.uboot-aurora.version;
    patches = [ ];
  });
  mesa = (final.callPackage ./mesa.nix {
    inherit (prev) mesa;
    src = source "mesa-aurora";
    inherit (pins.mesa-aurora) version commit;
  }).overrideAttrs (old: {
    # Preserve the conventional interface without retaining LLVM in GL's closure.
    passthru = old.passthru // { opencl = final.aurora-rusticl; };
  });
  aurora-lavapipe = final.callPackage ./lavapipe.nix {
    inherit (prev) mesa;
    src = source "mesa-aurora";
    inherit (pins.mesa-aurora) version commit;
  };
  aurora-rusticl = final.callPackage ./rusticl.nix {
    inherit (prev) mesa;
    src = source "mesa-aurora";
    inherit (pins.mesa-aurora) version commit;
  };
  aurora-fex-mesa = x86.callPackage ./pkgs/fex-mesa.nix {
    pin = pins.mesa-aurora;
    mesa64 = guestMesa x86;
    mesa32 = guestMesa x86_32;
  };
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
  mutter = prev.mutter.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ map stableFile [
      ./patches/mutter-prefer-variable-refresh-rate.patch
      ./patches/mutter-pq-reference-luminance.patch
    ];
  });
  # nixpkgs exposes a symlink join here: overriding its src does not replace
  # the inner model derivation. Build the pinned models explicitly, then merge
  # them ahead of the native common UCM definitions.
  alsa-ucm-conf-asahi = final.callPackage ./pkgs/ucm.nix {
    src = source "alsa-ucm-conf-aurora";
    pin = pins.alsa-ucm-conf-aurora;
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
  bankstown-lv2 = prev.bankstown-lv2.overrideAttrs (_old: {
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
  aurora-camera-denoise = final.callPackage ./pkgs/camera-denoise.nix {
    src = source "camera-denoise";
    pin = pins.camera-denoise;
  };
  # The keyboard backlight that follows the ambient light sensor, a system
  # service. modules/kbd-light.nix enables it and writes its settings.
  aurora-kbd-light = final.callPackage ./pkgs/kbd-light.nix {
    src = source "kbd-light";
    pin = pins.kbd-light;
  };
  aurora-bless = rustPackage "aurora-bless" ./locks/aurora-bless.Cargo.lock {
    cargoBuildFlags = [ "-p" "asahi-bless" ];
    cargoTestFlags = [ "-p" "asahi-bless" "-p" "apple-nvram" "-p" "asahi-nvram" ];
  };
}
