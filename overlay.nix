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
    version = "${old.version}-aurora3";
    # Keep the upstream archive tag when only changing the carry release.
    src = prev.plymouth.src;
    passthru = (old.passthru or { }) // { scriptKeyboardLifetime = 1; };
    nativeCheckInputs = (old.nativeCheckInputs or [ ]) ++ [ final.xvfb final.fontconfig final.dejavu_fonts ];
    patches = (old.patches or [ ]) ++ [
      # Fedora's two upstream fixes, in Fedora's order: the frame-buffer plugin
      # no longer opens the fbdev of a DRM device plymouth already drives, and
      # the default XKB keymap no longer overrides KEYMAP.
      (stableFile ./plymouth/0001-ply-device-manager-Fix-race-in-fb_device_has_drm_dev.patch)
      (stableFile ./plymouth/0001-ply-device-manager-fix-default-XKB-keymap-fallback-o.patch)
      (stableFile ./plymouth/0001-ply-terminal-Keep-terminal-input-nonblocking.patch)
      (stableFile ./plymouth/0001-systemd-units-Start-plymouthd-without-waiting-for-coldplug.patch)
      (stableFile ./plymouth/0001-Fix-splash-keyboard-lifetime.patch)
      # Clear the previous DRM master's HDR state before the SDR splash scans out.
      (stableFile ./plymouth/0002-drm-Reset-inherited-HDR-connector-state-before-SDR.patch)
      # Dirty only the copied areas: a full-buffer flush makes simpledrm copy the
      # whole boot framebuffer for every animation frame.
      (stableFile ./plymouth/0003-drm-Flush-only-the-damaged-areas.patch)
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
      $CC -D_GNU_SOURCE -Wall \
        -I. -I.. -I../src/libply -I../src/libply-splash-core \
        $($PKG_CONFIG --cflags libdrm libevdev) \
        ${stableFile ./plymouth/test-drm-damage.c} -o test-drm-damage \
        -Lsrc/libply-splash-core -Lsrc/libply \
        -Wl,-rpath,"$PWD/src/libply-splash-core" \
        -Wl,-rpath,"$PWD/src/libply" \
        -lply-splash-core -lply $($PKG_CONFIG --libs libdrm libevdev) -lm
      timeout 15s ./test-drm-damage
    '';
  });
  docker_29 = prev.docker_29.override { buildGoModule = dockerPolicyBuilder; };
  docker = final.docker_29;
  aurora-logos = final.callPackage ./logos/package.nix { };
  plymouth-theme-aurora = final.callPackage ./plymouth-theme-aurora/package.nix { };
  kdePackages = prev.kdePackages.overrideScope (_: kdePrev: {
    # Opt-in ambient white point in Night Light (AmbientWhitePoint in kwinrc,
    # off by default), fed by iio-sensor-proxy's ColorTemperature. The same
    # patch is in fedora-aurora's and alarm-aurora's kwin packages.
    kwin = kdePrev.kwin.overrideAttrs (old: {
      patches = (old.patches or [ ]) ++ map stableFile [
        ./patches/kwin-nightlight-ambient-white-point.patch
      ];
    });
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
  # The ambient light's colour temperature as SensorProxy's ColorTemperature,
  # from the IIO in_colortemp_input channel. The same patch is in
  # fedora-aurora's and alarm-aurora's iio-sensor-proxy packages.
  iio-sensor-proxy = prev.iio-sensor-proxy.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ [
      (stableFile ./patches/iio-sensor-proxy-ambient-colour-temperature.patch)
    ];
    # Run the integration tests, which include one for the colour channel.
    postPatch = (old.postPatch or "") + ''
      patchShebangs tests
    '';
    mesonFlags = (old.mesonFlags or [ ]) ++ [ (final.lib.mesonBool "tests" true) ];
    nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [
      final.gobject-introspection
      final.umockdev
      (final.python3.withPackages (p: [ p.dbus-python p.python-dbusmock p.pygobject3 p.psutil ]))
    ];
    checkInputs = (old.checkInputs or [ ]) ++ [ final.umockdev ];
    nativeCheckInputs = (old.nativeCheckInputs or [ ]) ++ [ final.dbus ];
    doCheck = true;
    # The Qualcomm SSC tests need SSC services that the sandbox lacks; they
    # fail the same way on the unpatched 3.9.
    checkPhase = ''
      runHook preCheck
      meson test --no-rebuild --print-errorlogs $(meson test --no-rebuild --list 2>/dev/null | grep -v ssc)
      runHook postCheck
    '';
  });
  # Opt-in ambient white point in the colour plugin
  # (org.gnome.settings-daemon.plugins.color ambient-white-point-enabled, off
  # by default). The same patch is in fedora-aurora's and alarm-aurora's
  # gnome-settings-daemon packages.
  gnome-settings-daemon = prev.gnome-settings-daemon.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ [
      (stableFile ./patches/gnome-settings-daemon-ambient-white-point.patch)
    ];
    nativeCheckInputs = (old.nativeCheckInputs or [ ]) ++ [ final.dbus ];
    doCheck = true;
    checkPhase = ''
      runHook preCheck
      export XDG_DATA_DIRS="${final.gsettings-desktop-schemas}/share/gsettings-schemas/${final.gsettings-desktop-schemas.name}''${XDG_DATA_DIRS:+:$XDG_DATA_DIRS}"
      meson test --no-rebuild --print-errorlogs gcm-self-test ambient-policy ambient-service
      runHook postCheck
    '';
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
      ./sep/0010-let-a-front-end-ask-whether-the-reader-needs-the-password.patch
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
      # Looks up fp_device_get_password_required() from libfprint 0010 at run time.
      ./sep/0004-dont-ask-for-a-finger-the-reader-will-not-take.patch
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
  aurora-power-budget = final.callPackage ./power-budget.nix { };
  # The legacy-to-speakerguardd-v2 upgrade tool (modules/speaker-upgrade.nix).
  aurora-speaker-upgrade = final.callPackage ./aurora-speaker-upgrade.nix {
    src = source "aurora-speaker-upgrade";
    version = pins.aurora-speaker-upgrade.version;
  };
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
  # 1008: a retry on a PCM that a system sleep suspended is an info line.
  # 1009: display audio nodes carry the ELD product name (upstream efb5aa06).
  # 1010: a stream whose start the driver refused is prepared again on the next
  # start (it failed every later start with -EPIPE until PipeWire restarted).
  # 1000-1004: AirPlay (RAOP)
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
      ./patches/pipewire/1009-alsa-put-the-ELD-product-name-on-HDMI-DP-nodes.patch
      ./patches/pipewire/1010-alsa-prepare-a-stream-again-after-its-start-failed.patch
    ];
    doCheck = true;
  });
  # AirPlay 2 receivers (services.shairport-sync with nqptp): nqptp's main loop
  # polled with a 10 ms select() timeout, so its SCHED_FIFO thread woke 100
  # times a second with no AirPlay session and held a CPU cluster at its top
  # performance state (0.3-1.4 W at idle on Aurora's Macs). Fedora's nqptp
  # 1.2.9 carries this patch; it blocks until a packet arrives or a clock is
  # waiting to be awakened. Same file as fedora-aurora packages/nqptp.
  nqptp = prev.nqptp.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ [ (stableFile ./patches/nqptp-1.2.9-idle-wakeups.patch) ];
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
      src = source "kernel-aurora" // { rev = pins.kernel-aurora.commit; };
      pin = pins.kernel-aurora;
      llvmPackages = kernelLLVM;
      inherit kernelCtxrExecmem kernelDtbAbi;
      kernelPatches = _kernelPatches;
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
  # loud_comp reports 7680 frames of latency at every FFT size while delaying
  # exactly the FFT size (1024 in every speaker graph): filter-chain then
  # published 7.5x that node's delay and AirPlay receivers ran ~150 ms early.
  # The patch (fedora-aurora#27, rebased on 1.2.37) reads the latency after the
  # new FFT rank is set. The install check runs every plugin the speaker graphs
  # use and compares its latency port with the measured impulse delay.
  lsp-plugins = prev.lsp-plugins.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ [
      (stableFile ./patches/lsp-plugins/1000-loud_comp-report-the-latency-of-the-FFT-size-in-use.patch)
    ];
    nativeInstallCheckInputs = (old.nativeInstallCheckInputs or [ ]) ++ [ final.lilv final.pkg-config ];
    doInstallCheck = true;
    installCheckPhase = ''
      runHook preInstallCheck
      $CC -O2 -o lsp-latency-check ${stableFile ./patches/lsp-plugins/lsp-latency-check.c} $(pkg-config --cflags --libs lilv-0) -lm
      LV2_PATH=$out/lib/lv2 ./lsp-latency-check
      runHook postInstallCheck
    '';
  });
  asahi-audio = prev.asahi-audio.overrideAttrs (old: {
    src = source "aurora-audio";
    version = "${pins.aurora-audio.version}-aurora15";
    patches = (old.patches or [ ]) ++ [ (stableFile ./patches/0001-restore-legacy-speaker-graphs.patch) ];
    postInstall = (old.postInstall or "") + ''
      echo ${pins.aurora-audio.commit} > "$out/.aurora-audio-commit"
      test -e "$out/share/wireplumber/scripts/device/asahi-keep-profile.lua"
      # MCA speaker PCMs wake on period interrupts: a chrony slew no longer
      # re-prepares the timer-scheduled sink (aurora-audio 4.1-14 on Fedora/ALARM).
      install -Dm644 ${stableFile ./patches/99-aurora-speaker-irq.conf} "$out/share/wireplumber/wireplumber.conf.d/99-aurora-speaker-irq.conf"
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
    # Downstream: a sense period read after a startup probe closed the speakers
    # is skipped instead of panicking the daemon (every boot and PipeWire restart
    # on an M2 Air). Any other invalid rate still fails safe. Same change as
    # fedora-aurora/alarm-aurora speakersafetyd 2.0.1, on nixpkgs' 3.0.0.
    patches = (old.patches or [ ]) ++ [
      (stableFile ./speakersafetyd/0001-skip-a-sense-period-read-after-a-probe-closed-the-speakers.patch)
    ];
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
  # daemon above. Opt-in: modules/speakerguardd-v2.nix installs it only with
  # aurora.speakerguardd.v2.enable (default false), and even then its gate
  # keeps speakersafetyd in charge until aurora-speaker-upgrade switches.
  speakerguardd-v2 = let
    # The crates this package ships; the rig and benchmark crates stay out.
    crates = [ "-p" "sgv2-core" "-p" "sgv2-lv2" "-p" "sgv2-supervisor" "-p" "aurora-speaker-tuning" ];
    units = [ "speakerguardd.service" "speakerguardd-provision.service" "speakerguardd-selfcheck.service"
              "speakerguardd-switchtest.service" "speakerguardd-seat.service" "speakerguardd-seat.path" "speakerguardd-sleep.service" ];
    userUnits = [ "speakerguardd-session.service" "speakerguardd-graph.service" ];
  in rustPackage "speakerguardd-v2" ./locks/speakerguardd-v2.Cargo.lock {
    cargoBuildFlags = crates;
    cargoTestFlags = crates;
    # RC8.2+ knows the dual-interface kernel (linux#1279: "Speaker Volume
    # Unlock" by default, v2's lease only after the root-only switch). A v2
    # older than speakerguardd#117/#131/#134 (e.g. 0.31) refuses on that kernel
    # and leaves the speakers silent (safe, at the kernel lock): the module
    # asserts this flag, and postPatch proves it from the sources.
    passthru.dualInterface = true;
    postPatch = ''
      grep -q "def interface" packaging/session/speakerguardd-gate || { echo "speakerguardd-v2: these sources do not know the dual-interface kernel (speakerguardd#117)"; exit 1; }
    '';
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
      # The macOS parity attestations speakerguardd-selfcheck verify reads
      # (speakerguardd#114); a missing file refuses every Mac.
      install -Dm644 packaging/session/parity.json -t $out/share/speakerguardd
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
      # The switch test runs after login, before the supervisor (speakerguardd#102).
      grep -qx 'Requires=speakerguardd-v2-switchtest.service' $sd/speakerguardd-v2.service
      grep -qx 'After=speakerguardd-v2-selfcheck.service systemd-user-sessions.service' $sd/speakerguardd-v2-switchtest.service
      grep -qx "ExecCondition=$lx/speakerguardd-selfcheck pending" $sd/speakerguardd-v2-switchtest.service
      grep -qx "ExecStopPost=$lx/speakerguardd-selfcheck pending --clear" $sd/speakerguardd-v2-switchtest.service
      grep -qx "ExecStop=$lx/speakerguardd-provision wake --unit speakerguardd-v2.service" $sd/speakerguardd-v2-sleep.service
      # The supervisor and the sleep hooks need a qualified board (gate v2);
      # provisioning, the seat follower and the silent self-check run first,
      # in the gate's prepare mode, and produce the records that qualify it.
      for u in speakerguardd-v2 speakerguardd-v2-sleep; do
        grep -qx "ExecCondition=$lx/speakerguardd-gate v2" $sd/$u.service
      done
      for u in speakerguardd-v2-provision speakerguardd-v2-selfcheck speakerguardd-v2-seat; do
        grep -qx "ExecCondition=$lx/speakerguardd-gate prepare" $sd/$u.service
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
  # package's own lib/aurora-camera-denoise: cdn-backend-ave.so (the video
  # encoder's temporal filter, the default where the kernel has it) and
  # cdn-backend-ane.so (the Neural Engine low-light stage) are built here. Settings come from /etc, which
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
  # Bring-up diagnostics, opt-in: modules/diag.nix installs it when
  # aurora.diag.enable is set.
  aurora-diag = final.callPackage ./pkgs/aurora-diag.nix {
    src = source "aurora-diag";
    pin = pins.aurora-diag;
  };
  # OpenSSH ecdsa-sk keys in the Secure Enclave (aurora-sep-userspace sk/):
  # the provider library, the udev rule giving the sep-key group /dev/sep-key
  # and its sysusers entry. modules/sep.nix installs it and makes the group.
  aurora-sep-sk = final.stdenv.mkDerivation {
    pname = "aurora-sep-sk";
    version = pins.aurora-sep-sk.version;
    src = source "aurora-sep-sk";
    sourceRoot = "${pins.aurora-sep-sk.archive_root}/sk";
    nativeBuildInputs = [ final.pkg-config ];
    buildInputs = [ final.openssl ];
    # The OpenSSH flow against software P-256 stand-ins: no root, no hardware.
    # Client tools only, as in the Fedora build: no sshd login in the sandbox.
    nativeCheckInputs = [
      (final.runCommand "openssh-client-tools" { } ''
        mkdir -p $out/bin
        for t in ssh ssh-keygen ssh-agent ssh-add; do ln -s ${final.openssh}/bin/$t $out/bin/$t; done
      '')
      final.gitMinimal
    ];
    makeFlags = [
      "PREFIX=${placeholder "out"}" "LIBDIR=${placeholder "out"}/lib"
      "UDEVRULESDIR=${placeholder "out"}/lib/udev/rules.d" "SYSUSERSDIR=${placeholder "out"}/lib/sysusers.d"
    ];
    doCheck = true;
    checkTarget = "check";
    postInstall = ''
      install -Dm644 ../docs/ssh-sk.md $out/share/doc/aurora-sep-sk/ssh-sk.md
    '';
    passthru.commit = pins.aurora-sep-sk.commit;
    meta = {
      description = "OpenSSH security-key provider for Secure Enclave keys";
      homepage = "https://github.com/aurora-silicon/aurora-sep-userspace";
      license = final.lib.licenses.mit;
      platforms = [ "aarch64-linux" ];
    };
  };
  # Secure Enclave LUKS2 unlock (aurora-sep-userspace luks/): aurora-sep-cryptenroll,
  # aurora-sep-fde (password-sealed volumes with owners), the cryptsetup token
  # plugin, pam_aurora_sep_fde and the initrd loader. modules/sep-luks.nix
  # installs it when asked.
  aurora-sep-luks = final.stdenv.mkDerivation {
    pname = "aurora-sep-luks";
    version = pins.aurora-sep-luks.version;
    src = source "aurora-sep-luks";
    sourceRoot = "${pins.aurora-sep-luks.archive_root}/luks";
    nativeBuildInputs = [ final.pkg-config ];
    buildInputs = [ final.cryptsetup final.json_c final.pam ];
    makeFlags = [
      "PREFIX=${placeholder "out"}"
      "TOKENDIR=${placeholder "out"}/lib/cryptsetup"
      "LIBEXECDIR=${placeholder "out"}/libexec"
      "PAMDIR=${placeholder "out"}/lib/security"
      # The default fde.conf; modules/sep-luks.nix links it to /etc/aurora-sep.
      "SYSCONFDIR=${placeholder "out"}/etc"
    ];
    # install-initrd adds the initrd loader and units that
    # aurora.sepLuks.initrd uses; the dracut/mkinitcpio parts are not needed.
    installTargets = [ "install" "install-initrd" ];
    # Kernel "user" keys stand in for the SEP. The test exits 77 when the
    # sandbox blocks the keyring. Kernels with af_alg_restrict refuse an
    # unprivileged ccm(aes) bind with ENOENT, which stops the test at its seal
    # step after the encoding checks have passed; that alone is not a failure
    # here. The LUKS2 file-image tests need root and run in
    # aurora-sep-userspace's CI. Any other failure fails the build.
    doCheck = true;
    checkPhase = ''
      runHook preCheck
      make test/test-seal
      status=0
      ./test/test-seal > test-seal.log 2>&1 || status=$?
      cat test-seal.log
      if [ "$status" = 1 ] && [ "$(grep -c '^FAIL' test-seal.log)" = 1 ] &&
         grep -qx 'seal failed: No such file or directory' test-seal.log; then
        echo "AF_ALG ccm(aes) is restricted in this build root; seal round trip not run"
      elif [ "$status" != 0 ] && [ "$status" != 77 ]; then
        exit 1
      fi
      runHook postCheck
    '';
    postInstall = ''
      for doc in luks-sep.md luks-sep-initrd.md luks-sep-owners.md; do
        install -Dm644 ../docs/$doc $out/share/doc/aurora-sep-luks/$doc
      done
      # pam_aurora_sep_fde is built only when pkg-config finds pam.
      test -e $out/lib/security/pam_aurora_sep_fde.so
    '';
    passthru.commit = pins.aurora-sep-luks.commit;
    meta = {
      description = "Unlock LUKS2 volumes with the Apple Secure Enclave";
      homepage = "https://github.com/aurora-silicon/aurora-sep-userspace";
      license = final.lib.licenses.mit;
      mainProgram = "aurora-sep-cryptenroll";
      platforms = [ "aarch64-linux" ];
    };
  };
  # Touch ID as a FIDO2/U2F security key (aurora-sep-userspace fido/).
  # modules/fido.nix runs it with aurora.fido.enable; off by default.
  aurora-fido = let
    # jeepney: the per-user agent's D-Bus front-end (vault = user).
    py = final.python3.withPackages (ps: [ ps.cryptography ps.jeepney ]);
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
      for f in $out/bin/aurora-fido $out/libexec/aurora-fido/aurora-fidod \
               $out/libexec/aurora-fido/aurora-passkeyd; do
        substituteInPlace $f --replace-fail "#!/usr/bin/python3 -I" "#!${py.interpreter} -I"
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
    cargoTestFlags = [ "-p" "asahi-bless" "-p" "apple-nvram" "-p" "aurora-nvram" ];
  };
  # NVRAM reader/writer from the aurora-bless workspace; parses the NVRAM v3
  # stores of current Macs. asahi-nvram stays as a name for old scripts.
  aurora-nvram = rustPackage "aurora-bless" ./locks/aurora-bless.Cargo.lock {
    pname = "aurora-nvram";
    cargoBuildFlags = [ "-p" "aurora-nvram" ];
    cargoTestFlags = [ "-p" "aurora-nvram" ];
    postInstall = ''
      ln -s aurora-nvram $out/bin/asahi-nvram
      install -Dm644 aurora-nvram/README.md NEO.md -t $out/share/doc/aurora-nvram
      install -Dm644 LICENSE $out/share/licenses/aurora-nvram/LICENSE
    '';
    passthru.commit = pins.aurora-bless.commit;
    meta = {
      description = "Read and write NVRAM variables on Apple Silicon Macs";
      homepage = "https://github.com/aurora-silicon/aurora-bless";
      license = final.lib.licenses.mit;
      mainProgram = "aurora-nvram";
      platforms = [ "aarch64-linux" ];
    };
  };
  # Bluetooth pairings made in macOS, copied into BlueZ's storage
  # (modules/btsync.nix), from the aurora-bless workspace.
  aurora-btsync = rustPackage "aurora-bless" ./locks/aurora-bless.Cargo.lock {
    pname = "aurora-btsync";
    nativeBuildInputs = [ final.pkg-config ];
    buildInputs = [ final.dbus ];
    cargoBuildFlags = [ "-p" "aurora-btsync" ];
    cargoTestFlags = [ "-p" "aurora-btsync" ];
    postInstall = ''
      ln -s aurora-btsync $out/bin/asahi-btsync
      unit=$out/lib/systemd/system/aurora-btsync.service
      install -Dm644 aurora-btsync/etc/systemd/system/aurora-btsync.service $unit
      substituteInPlace $unit --replace-fail /usr/bin/aurora-btsync $out/bin/aurora-btsync
      ln -s aurora-btsync.service $out/lib/systemd/system/asahi-btsync.service
      install -Dm644 aurora-btsync/etc/udev/rules.d/96-aurora-btsync.rules $out/lib/udev/rules.d/96-aurora-btsync.rules
      install -Dm644 aurora-btsync/README.md -t $out/share/doc/aurora-btsync
      install -Dm644 LICENSE $out/share/licenses/aurora-btsync/LICENSE
    '';
    passthru.commit = pins.aurora-bless.commit;
    meta = {
      description = "Use the Bluetooth pairings made in macOS on Linux";
      homepage = "https://github.com/aurora-silicon/aurora-bless";
      license = final.lib.licenses.mit;
      mainProgram = "aurora-btsync";
      platforms = [ "aarch64-linux" ];
    };
  };
  # The built-in panel's brightness shared with the boot loader through NVRAM
  # backlight-nits (modules/panel-nits.nix), from the aurora-bless workspace.
  aurora-panel-nits = rustPackage "aurora-bless" ./locks/aurora-bless.Cargo.lock {
    pname = "aurora-panel-nits";
    cargoBuildFlags = [ "-p" "aurora-panel-nits" ];
    cargoTestFlags = [ "-p" "aurora-panel-nits" ];
    postInstall = ''
      dropin="$out/lib/systemd/system/systemd-backlight@backlight:apple-panel-bl.service.d"
      install -Dm644 aurora-panel-nits/systemd/aurora-panel-nits.service $out/lib/systemd/system/aurora-panel-nits.service
      install -Dm644 aurora-panel-nits/systemd/50-aurora-panel-nits.conf "$dropin/50-aurora-panel-nits.conf"
      install -Dm644 aurora-panel-nits/systemd/90-aurora-panel-nits.rules $out/lib/udev/rules.d/90-aurora-panel-nits.rules
      substituteInPlace $out/lib/systemd/system/aurora-panel-nits.service "$dropin/50-aurora-panel-nits.conf" \
        --replace-fail /usr/bin/aurora-panel-nits $out/bin/aurora-panel-nits
    '';
    passthru.commit = pins.aurora-bless.commit;
    meta = {
      description = "Built-in panel brightness shared with the boot loader through NVRAM";
      homepage = "https://github.com/aurora-silicon/aurora-bless";
      license = final.lib.licenses.mit;
      mainProgram = "aurora-panel-nits";
      platforms = [ "aarch64-linux" ];
    };
  };
}
