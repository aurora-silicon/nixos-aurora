final: prev:
let
  pins = builtins.fromJSON (builtins.readFile ./sources.json);
  source = name: final.fetchurl {
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
  linux-asahi = final.lib.makeOverridable ({ _kernelPatches ? [ ] }:
    final.lib.recurseIntoAttrs (final.linuxPackagesFor (final.buildLinux {
      pname = "linux-aurora";
      version = "7.2.10";
      modDirVersion = "7.2.10";
      src = source "kernel-aurora";
      extraMeta.branch = "7.2";
      kernelPatches = [ { name = "Aurora Rust drivers"; patch = null; features.rust = true; } ] ++ _kernelPatches;
      structuredExtraConfig = with final.lib.kernel; {
      ARM64_4K_PAGES = no;
      ARM64_16K_PAGES = yes;
      DRM_ASAHI = module;
      RUST = yes;
      APPLE_WATCHDOG = yes;
      APPLE_M1_CPU_PMU = yes;
      SERIAL_APPLE_DOCKCHANNEL = yes;
      SERIAL_APPLE_DOCKCHANNEL_EARLYCON = yes;
      PCIE_APPLE_PIODMA_DIAG = yes;
      MT7932_FULLMAC = module;
      BT_MTK7932_PCIE = module;
      SPI_APPLE_QSPI = module;
      RTC_DRV_APPLE_PMU = module;
      SND_SOC_APPLE_T8140_AOP_AUDIO = module;
      DRM_ACCEL_ANE = module;
      TRUSTED_KEYS = yes;
      APPLE_SEP = yes;
    };
    }))) { };
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
  mesa = (prev.mesa.override {
    galliumDrivers = [ "asahi" "zink" "softpipe" ];
    vulkanDrivers = [ "asahi" ];
  }).overrideAttrs (old: {
    src = source "mesa-aurora";
    version = pins.mesa-aurora.version;
    patches = [ ];
  });
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
    '';
  };
  aurora-bless = rustPackage "aurora-bless" ./locks/aurora-bless.Cargo.lock {
    cargoBuildFlags = [ "-p" "asahi-bless" ];
    cargoTestFlags = [ "-p" "asahi-bless" "-p" "apple-nvram" "-p" "asahi-nvram" ];
  };
}
