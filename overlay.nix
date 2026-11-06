final: prev:
let
  # True once the pinned aura has no monitor (aura#77); its build checks this
  # against the source. Such an aura moves the kernel into the CTXR window, so it
  # needs kernelCtxrExecmem.
  auraMonitorFree = true;
  # True with a kernel pin whose configuration resolves CONFIG_ARM64_CTXR_EXECMEM=y
  # (aurora-silicon/linux#985), which keeps every kernel code page inside that
  # window. The kernel build checks this against its configuration.
  kernelCtxrExecmem = true;
  # The DT ABI generation of the kernel's device trees, the integer fedora-aurora
  # ships as packages/kernel-aurora/dtb-abi. Raise it only for a device tree
  # change older kernels cannot boot with: Stage 2 updates then wait until no
  # configuration GRUB lists has an older generation (docs/updates.md).
  kernelDtbAbi = let value = final.lib.fileContents ./kernel/dtb-abi; in
    assert final.lib.assertMsg (builtins.match "0|[1-9][0-9]*" value != null)
      "kernel/dtb-abi must hold one non-negative integer";
    final.lib.toInt value;
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
    version = "${old.version}-aurora2";
    # Keep the upstream archive tag when only changing the carry release.
    src = prev.plymouth.src;
    passthru = (old.passthru or { }) // { scriptKeyboardLifetime = 1; };
    nativeCheckInputs = (old.nativeCheckInputs or [ ]) ++ [ final.xvfb final.fontconfig final.dejavu_fonts ];
    patches = (old.patches or [ ]) ++ [
      (stableFile ./plymouth/0001-ply-terminal-Keep-terminal-input-nonblocking.patch)
      (stableFile ./plymouth/0001-systemd-units-Start-plymouthd-without-waiting-for-coldplug.patch)
      (stableFile ./plymouth/0001-Fix-splash-keyboard-lifetime.patch)
      # Clear the previous DRM master's HDR state before the SDR splash scans out.
      (stableFile ./plymouth/0002-drm-Reset-inherited-HDR-connector-state-before-SDR.patch)
    ];
    doCheck = true;
    postCheck = (old.postCheck or "") + ''
      export FONTCONFIG_FILE=${final.makeFontsConf { fontDirectories = [ final.dejavu_fonts ]; }}
      bash ${stableFile ./plymouth/check-keyboard-lifetime.sh} "$PWD/.." "$PWD" ${./plymouth}
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
  plymouth-theme-aurora = final.callPackage ./plymouth-theme-aurora/package.nix { };
  kdePackages = prev.kdePackages.overrideScope (_: kdePrev: {
    kinfocenter = kdePrev.kinfocenter.overrideAttrs (old: {
      patches = (old.patches or [ ]) ++ map stableFile [
        ./patches/kinfocenter-unknown-memory.patch
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
      ./sep/0007-aurora-name-retry-causes-and-keep-waiting.patch
      ./sep/0008-aurora-report-the-touch-id-lockout-as-locked-out.patch
      ./sep/0009-aurora-say-why-touch-id-needs-the-password.patch
    ];
    postPatch = (old.postPatch or "") + ''
      install -Dm644 ${stableFile ./sep/apple-sep.h} aurora-uapi/linux/apple-sep.h
      ${final.python3.interpreter} ${stableFile ./sep/test_interface.py} libfprint/drivers/aurora/aurora.c aurora-uapi/linux/apple-sep.h
      ${final.python3.interpreter} ${stableFile ./sep/test_lockout_reason.py} libfprint/drivers/aurora/aurora.c
    '';
    preConfigure = (old.preConfigure or "") + ''
      export CFLAGS="''${CFLAGS:-} -I$PWD/aurora-uapi"
    '';
  });
  fprintd = prev.fprintd.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ map stableFile [
      ./sep/0001-preserve-print-on-device-delete-failure.patch
      # Needs FP_DEVICE_ERROR_LOCKED_OUT from libfprint 0008 above.
      ./sep/0002-report-lockout-and-fall-back-to-the-password.patch
      # Needs FP_DEVICE_ERROR_PASSWORD_REQUIRED{,_AFTER_BOOT} from libfprint 0009.
      ./sep/0003-say-why-the-reader-needs-the-password.patch
    ];
    postPatch = (old.postPatch or "") + ''
      ${final.python3.interpreter} ${stableFile ./sep/test_account_gate.py} src/device.c
    '';
  });
  # Re-arms Touch ID with the password after a lockout: the PAM module that
  # modules/sep.nix puts after pam_unix, and the root service it asks.
  aurora-touchid-rearm = final.stdenv.mkDerivation {
    pname = "aurora-touchid-rearm";
    version = pins.aurora-touchid-rearm.version;
    src = source "aurora-touchid-rearm";
    buildInputs = [ final.pam ];
    nativeCheckInputs = [ final.python3 ];
    makeFlags = [
      "-C" "touchid-rearm" "WARN=-Wall"
      "LIBEXECDIR=${placeholder "out"}/libexec" "PAMDIR=${placeholder "out"}/lib/security"
      "PAMCONFDIR=${placeholder "out"}/lib/pam.d" "UNITDIR=${placeholder "out"}/lib/systemd/system"
      "DOCDIR=${placeholder "out"}/share/doc/aurora-touchid-rearm"
      "SYSCONFDIR=${placeholder "out"}/etc"
    ];
    doCheck = true;
    checkTarget = "check";
    AURORA_TEST_PAM_DIR = "${final.pam}/lib/security";
    passthru.commit = pins.aurora-touchid-rearm.commit;
    meta = {
      description = "Re-arm Touch ID with the password after a lockout";
      homepage = "https://github.com/aurora-silicon/aurora-sep-userspace";
      license = final.lib.licenses.gpl2Only;
      platforms = final.lib.platforms.linux;
    };
  };
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
  # PipeWire with the patches fedora-aurora and alarm-aurora carry, for the
  # daemon (modules/audio.nix sets it as services.pipewire.package). It is a
  # separate attribute, not a replacement for pipewire: clients that link
  # libpipewire (SDL, Qt, the portals, the compositors) keep nixpkgs' cached
  # builds, and the fixed code runs where the speaker graph runs, in the
  # daemon's filter-chain. 1006: filter-graph keeps the software volume at
  # unity on every volume or mute update, so a repeated write no longer
  # applies the speaker volume twice (-31 dB at a 30 % slider). 1005: it
  # follows its plugins' latency after activation. 1007: spa-alsa waits a
  # period after a refused start and reports refusals at most once per 5 s;
  # 1008: a retry on a PCM that a system sleep suspended is an info line. 1000-1004: AirPlay (RAOP)
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
      ./patches/pipewire/1008-alsa-a-start-on-a-suspended-PCM-is-expected-not-an-error.patch
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
      inherit kernelCtxrExecmem kernelDtbAbi;
      kernelPatches = [ {
        name = "restore-legacy-speaker-protection";
        patch = stableFile ./patches/0001-restore-legacy-speaker-protection.patch;
      } ] ++ _kernelPatches;
    }))) { };
  # Keep m1n1.override { customLogo = ...; } available to installed systems.
  m1n1 = assert final.lib.assertMsg (auraMonitorFree -> kernelCtxrExecmem)
    "aura without the monitor needs a kernel built with CONFIG_ARM64_CTXR_EXECMEM=y";
    import ./pkgs/aura.nix {
    inherit (final) lib rustPlatform buildPackages;
    inherit (prev) m1n1;
    inherit auraMonitorFree;
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
    version = "${pins.aurora-audio.version}-aurora12";
    patches = (old.patches or [ ]) ++ [ (stableFile ./patches/0001-restore-legacy-speaker-graphs.patch) ];
    postInstall = (old.postInstall or "") + ''
      echo ${pins.aurora-audio.commit} > "$out/.aurora-audio-commit"
      test -e "$out/share/wireplumber/scripts/device/asahi-keep-profile.lua"
    '';
    # nixpkgs' fixup phase rewrites /usr paths to this output first.
    postFixup = (old.postFixup or "") + ''
      for board in j316 j413 j616 j700; do
        test -s "$out/share/asahi-audio/$board/graph.json"
        grep -q "$out/share/asahi-audio/$board/graph.json" "$out/share/wireplumber/wireplumber.conf.d/99-asahi.conf"
      done
      test -s "$out/share/asahi-audio/j700/48.wav"
    '';
    # asahi-audio#24: the built-in card stays on HiFi with nothing in the jack.
    passthru = (old.passthru or { }) // { keepsBuiltinProfile = true; legacySpeakerGraphs = true; };
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
  # Touch ID as a FIDO2/U2F security key (aurora-sep-userspace fido/).
  # modules/fido.nix runs it with aurora.fido.enable; off by default.
  aurora-fido = let
    py = final.python3.withPackages (ps: [ ps.cryptography ps.pygobject3 ]);
    typelibs = final.lib.makeSearchPath "lib/girepository-1.0"
      [ final.glib.out final.gobject-introspection ];
  in final.stdenv.mkDerivation {
    pname = "aurora-fido";
    version = pins.aurora-fido.version;
    src = source "aurora-fido";
    sourceRoot = "${pins.aurora-fido.archive_root}/fido";
    nativeBuildInputs = [ final.pkg-config final.makeWrapper py ];
    buildInputs = [ final.json_c ];
    makeFlags = [
      "PREFIX=${placeholder "out"}"
      "LIBEXECDIR=${placeholder "out"}/libexec/aurora-fido"
      "SYSCONFDIR=${placeholder "out"}/etc"
      "PYTHON=${py.interpreter}"
    ];
    # Unit tests: software stand-ins, no root, no hardware.
    doCheck = true;
    checkTarget = "check";
    postInstall = ''
      for f in $out/bin/aurora-fido $out/libexec/aurora-fido/aurora-fidod; do
        substituteInPlace $f --replace-fail "#!/usr/bin/python3 -I" "#!${py.interpreter} -I"
        wrapProgram $f --prefix GI_TYPELIB_PATH : ${typelibs}
      done
    '';
    passthru.commit = pins.aurora-fido.commit;
    meta = {
      description = "Touch ID as a FIDO2/U2F security key (opt in)";
      homepage = "https://github.com/aurora-silicon/aurora-sep-userspace";
      license = final.lib.licenses.mit;
      mainProgram = "aurora-fido";
      platforms = [ "aarch64-linux" ];
    };
  };
  # AirDrop over the Wi-Fi firmware's own AWDL (awdl0): the omdrop-awdl
  # helpers and the omdrop-plugin receiver. The kernel's brcmfmac already has
  # the AWDL interface (aurora-silicon/linux#24, #183, #213). Same contents and
  # patches as fedora-aurora's and alarm-aurora's omdrop-awdl; modules/awdl.nix
  # installs it with aurora.awdl.enable, off by default.
  omdrop-awdl = let
    py = final.python3.withPackages (ps: [ ps.libarchive-c ps.pillow ps.dbus-python ps.pygobject3 ]);
    plugin = let pin = pins.omdrop-awdl.extra_sources.omdrop-plugin; in final.fetchurl {
      name = "omdrop-plugin-${pin.commit}.tar.gz";
      url = pin.source_url;
      inherit (pin) sha256;
    };
    runtimePath = final.lib.makeBinPath [ py final.bash final.coreutils final.iproute2 final.iputils
      final.iw final.openssl final.procps final.util-linux final.gawk final.gnugrep final.gnused
      final.networkmanager final.systemd final.kmod final.findutils ];
  in final.stdenvNoCC.mkDerivation {
    pname = "omdrop-awdl";
    version = pins.omdrop-awdl.version;
    src = source "omdrop-awdl";
    sourceRoot = pins.omdrop-awdl.archive_root;
    patches = [
      # awdl-up: accept NetworkManager's per-network cloned MAC once connected.
      (stableFile ./patches/omdrop-awdl-0.10.5-stable-cloned-mac.patch)
      # AWDL windows follow the Wi-Fi link's 5 GHz channel, as macOS schedules them.
      (stableFile ./patches/omdrop-awdl-0.10.5-follow-infra-channel.patch)
      # Set AWDL's 5 GHz social channel (default 149), or macOS will not route to us.
      (stableFile ./patches/omdrop-awdl-0.10.5-5ghz-social-channel.patch)
    ];
    nativeBuildInputs = [ final.makeWrapper py ];
    postUnpack = ''
      tar -xzf ${plugin} -C "$NIX_BUILD_TOP"
    '';
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      lib=$out/libexec/omdrop
      install -d $lib/radio
      for f in userspace/*; do
        [ -f "$f" ] || continue
        install -m 755 "$f" $lib/
      done
      chmod 644 $lib/*_*.py $lib/*.sh
      install -m 755 userspace/radio/* $lib/radio/
      install -Dm644 packaging/awdl0.service $out/lib/systemd/system/awdl0.service
      install -Dm644 packaging/awdl-warmup.service $out/lib/systemd/system/awdl-warmup.service
      install -Dm755 packaging/omdrop-awdl-sleep $out/lib/systemd/system-sleep/omdrop-awdl
      install -Dm644 packaging/org.omarchy.omdrop.policy $out/share/polkit-1/actions/org.omarchy.omdrop.policy
      install -Dm644 README.md $out/share/doc/omdrop-awdl/README.md
      r=$NIX_BUILD_TOP/${pins.omdrop-awdl.extra_sources.omdrop-plugin.archive_root}
      v=$out/share/omdrop/receiver
      for f in airdrop-serve.py contacts.py debugdump.py identity.py lifecycle.py safeplist.py; do
        install -Dm644 $r/bin/$f $v/bin/$f
      done
      chmod 755 $v/bin/airdrop-serve.py
      install -Dm644 -t $v/bin/apple-ca $r/bin/apple-ca/*.pem
      # Apple's public root, which airdrop-serve.py loads at start (Contacts Only checks).
      install -Dm644 $r/share/certs/apple_root_ca.pem $v/share/certs/apple_root_ca.pem
      install -Dm644 $r/README.md $v/README.md
      install -Dm644 $r/share/airdrop-receiver.service $out/lib/systemd/user/airdrop-receiver.service
      # The receiver writes its identity into ~/.omdrop, which ProtectHome=read-only
      # keeps it from creating, so create both writable paths before the sandbox.
      sed -i -e "s#@PLUGIN_DIR@#$v#g" -e "s#/usr/bin/python3#${py.interpreter}#g" \
        -e '0,/^ExecStartPre=/s##ExecStartPre=+${final.coreutils}/bin/mkdir -p -m 0700 %h/.omdrop\nExecStartPre=+${final.coreutils}/bin/mkdir -p %h/Downloads\n&#' \
        $out/lib/systemd/user/airdrop-receiver.service
      # Store paths in place of the FHS ones; /usr/lib/omdrop-core is another package.
      find $lib $out/lib/systemd $out/share/polkit-1 -type f -exec \
        sed -i -E "s#/usr/lib/omdrop([/\"<' ]|\$)#$lib\1#g" {} +
      sed -i -e "s#/usr/bin/timeout #${final.coreutils}/bin/timeout #" $out/lib/systemd/system/awdl0.service
      runHook postInstall
    '';
    postFixup = ''
      patchShebangs $out/libexec/omdrop $out/share/omdrop $out/lib/systemd/system-sleep
      for f in $out/libexec/omdrop/awdl-up $out/libexec/omdrop/awdl-warmup $out/libexec/omdrop/omdrop-discoverable \
               $out/libexec/omdrop/send-to-peer $out/lib/systemd/system-sleep/omdrop-awdl; do
        wrapProgram $f --prefix PATH : ${runtimePath}
      done
    '';
    doInstallCheck = true;
    installCheckPhase = ''
      grep -q stable-ssid $out/libexec/omdrop/.awdl-up-wrapped
      grep -q '^follow_infra()' $out/libexec/omdrop/.awdl-up-wrapped
      grep -q awdl_osoc_chan $out/libexec/omdrop/omdrop-broadcom.sh
      test -s $out/share/omdrop/receiver/share/certs/apple_root_ca.pem
      if grep -rIl '/usr/lib/omdrop[/" ]' $out/libexec $out/lib $out/share/polkit-1; then exit 1; fi
      if grep -q '@PLUGIN_DIR@' $out/lib/systemd/user/airdrop-receiver.service; then exit 1; fi
      ${py.interpreter} -c 'import sys; sys.path.insert(0, "'$out'/libexec/omdrop"); import awdl_plist, awdl_identity'
    '';
    passthru.commit = pins.omdrop-awdl.commit;
    meta = {
      description = "AirDrop over firmware-native AWDL on Apple Silicon Macs (opt in)";
      homepage = "https://github.com/netmojo-systems/omdrop-awdl";
      license = with final.lib.licenses; [ gpl2Only mit ];
      platforms = [ "aarch64-linux" ];
    };
  };
  # Inspects the Linux side of the SEP and xART state and starts Touch ID over
  # (aurora-xart reset-touchid). modules/sep.nix installs it.
  aurora-xart = final.stdenvNoCC.mkDerivation {
    pname = "aurora-xart";
    version = pins.aurora-xart.version;
    src = source "aurora-xart";
    nativeBuildInputs = [ final.python3 ];
    dontBuild = true;
    doCheck = true;
    checkPhase = ''
      runHook preCheck
      make check PYTHON=${final.python3.interpreter}
      runHook postCheck
    '';
    installPhase = ''
      runHook preInstall
      make install DESTDIR=$out PREFIX=
      substituteInPlace $out/bin/aurora-xart \
        --replace-fail "#!/usr/bin/python3 -I" "#!${final.python3.interpreter} -I"
      runHook postInstall
    '';
    passthru.commit = pins.aurora-xart.commit;
    meta = {
      description = "Inspect and manage the Linux side of the Secure Enclave and xART state";
      homepage = "https://github.com/aurora-silicon/aurora-xart";
      license = final.lib.licenses.mit;
      mainProgram = "aurora-xart";
      platforms = [ "aarch64-linux" ];
    };
  };
  # Trial-then-commit Stage 2 updates (modules/installed.nix): fedora-aurora's
  # updater logic with its NixOS adapter.
  aurora-stage2 = final.callPackage ./stage2/package.nix { };
  aurora-bless = rustPackage "aurora-bless" ./locks/aurora-bless.Cargo.lock {
    cargoBuildFlags = [ "-p" "asahi-bless" ];
    cargoTestFlags = [ "-p" "asahi-bless" "-p" "apple-nvram" "-p" "asahi-nvram" ];
  };
}
