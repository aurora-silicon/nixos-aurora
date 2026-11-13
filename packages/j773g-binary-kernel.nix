{ lib, stdenvNoCC, kmod, kernelPayload ? ./j773g-kernel/run59
, kernelRelease ? "7.3.0-m4atlrx+"
, sourceCommit ? "b3218010d34be05fa0d6ebfb6fd08638ecdb7451"
, imageSha256 ? "13d3d96630b2cb68c5d3828819431fe5b4c851a4f40c0b498978ead27fe662e7"
, dtbSha256 ? "5a72db650a379a3320d2736be69a152c5836e16a3cb038a50f0d692180620e46"
, ...
}:

let
  # These values are checked against the shipped config in the install phase
  # and by tests. Keep the passthru small: linuxPackagesFor queries it during
  # module evaluation and must not parse the full 190 KiB config repeatedly.
  configValues = {
    BINFMT_ELF = "y";
    FW_LOADER = "y";
    MODULES = "y";
    APPLE_WATCHDOG = "y";
    NVME_APPLE = "y";
    BTRFS_FS = "y";
    EXT4_FS = "y";
    VFAT_FS = "y";
    RUST = "y";
    IP_NF_MATCH_RPFILTER = "n";
    NF_TABLES = "m";
  };
  kernelConfig = rec {
    isSet = name: builtins.hasAttr name configValues;
    getValue = name: if isSet name then configValues.${name} else null;
    isYes = name: getValue name == "y";
    isNo = name: getValue name == "n";
    isModule = name: getValue name == "m";
    isEnabled = name: isYes name || isModule name;
    isDisabled = name: !isEnabled name;
  } // builtins.listToAttrs (map (name: { name = "CONFIG_${name}"; value = configValues.${name}; }) (builtins.attrNames configValues));
in
stdenvNoCC.mkDerivation {
  pname = "linux-j773g-binary";
  version = kernelRelease;
  outputs = [ "out" "modules" "dev" "configfile" ];
  nativeBuildInputs = [ kmod ];
  dontUnpack = true;

  installPhase = ''
    runHook preInstall
    test "$(sha256sum ${kernelPayload}/Image | cut -d ' ' -f 1)" = ${imageSha256}
    test "$(sha256sum ${kernelPayload}/t8132-j773g.dtb | cut -d ' ' -f 1)" = ${dtbSha256}
    grep -aF "Linux version ${kernelRelease} " ${kernelPayload}/Image >/dev/null
    grep -qx 'CONFIG_APPLE_WATCHDOG=y' ${kernelPayload}/config
    grep -qx 'CONFIG_NVME_APPLE=y' ${kernelPayload}/config
    grep -qx 'CONFIG_NF_TABLES=m' ${kernelPayload}/config

    install -Dm0444 ${kernelPayload}/Image "$out/Image"
    install -Dm0444 ${kernelPayload}/t8132-j773g.dtb \
      "$out/dtbs/apple/t8132-j773g.dtb"
    install -Dm0444 ${kernelPayload}/config "$configfile"
    printf '%s\n' ${sourceCommit} > "$out/aurora-source-commit"

    moduleDir="$modules/lib/modules/${kernelRelease}"
    mkdir -p "$moduleDir" "$dev"
    touch "$moduleDir/modules.order" "$moduleDir/modules.builtin.modinfo"
    printf '%s\n' kernel/drivers/watchdog/apple_wdt.ko > "$moduleDir/modules.builtin"
    depmod -b "$modules" ${kernelRelease}
    runHook postInstall
  '';

  passthru = {
    modDirVersion = kernelRelease;
    kernelFile = "Image";
    target = "Image";
    dtbs = "dtbs";
    buildDTBs = true;
    isLTS = false;
    isZen = false;
    kernelAtLeast = lib.versionAtLeast kernelRelease;
    kernelOlder = lib.versionOlder kernelRelease;
    commonMakeFlags = [ ];
    config = kernelConfig;
    features = {
      ia32Emulation = false;
      efiBootStub = false;
      netfilterRPFilter = kernelConfig.isEnabled "IP_NF_MATCH_RPFILTER";
      # NF_TABLES is modular in the config, but the archived run-59 payload
      # contains no .ko files. Do not claim a feature the package cannot load.
      nftables = false;
    };
    auroraSourceCommit = sourceCommit;
    auroraDtbAbi = 1;
    auroraCtxrExecmem = true;
  };

  meta = {
    description = "Verified prebuilt Linux kernel for the Apple J773g";
    platforms = [ "x86_64-linux" "aarch64-linux" ];
    license = lib.licenses.gpl2Only;
  };
}
