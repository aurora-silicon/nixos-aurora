{ lib, stdenvNoCC, kmod, kernelPayload ? ./j773g-kernel/integration-0443-v2
, kernelRelease ? "7.3.0-m4atlrx+"
, sourceCommit ? "920ed134a628366563fd442aa55224d321caa1a7"
, imageSha256 ? "9b2f6aa0bb7b8740c3659312504ca07091494cd068b26b3543063d4341139eb0"
, dtbSha256 ? "d086e25ffa5a4bbe645a1c29448dc8c013af8eea89cda564113b47a7fd7b56b4"
, modulesSha256 ? "455854d97c192ee61237b65e253f36d474f12654c3f47bfbb29903437683c468"
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
    test "$(sha256sum ${kernelPayload}/modules.tar.gz | cut -d ' ' -f 1)" = ${modulesSha256}
    grep -aF "Linux version ${kernelRelease} " ${kernelPayload}/Image >/dev/null
    grep -qx 'CONFIG_APPLE_WATCHDOG=y' ${kernelPayload}/config
    grep -qx 'CONFIG_NVME_APPLE=y' ${kernelPayload}/config
    grep -qx 'CONFIG_NF_TABLES=m' ${kernelPayload}/config

    install -Dm0444 ${kernelPayload}/Image "$out/Image"
    install -Dm0444 ${kernelPayload}/t8132-j773g.dtb \
      "$out/dtbs/apple/t8132-j773g.dtb"
    install -Dm0444 ${kernelPayload}/config "$configfile"
    printf '%s\n' ${sourceCommit} > "$out/aurora-source-commit"

    mkdir -p "$modules" "$dev"
    tar -xzf ${kernelPayload}/modules.tar.gz -C "$modules"
    moduleDir="$modules/lib/modules/${kernelRelease}"
    rm -f "$moduleDir/build" "$moduleDir/source"
    test -s "$moduleDir/modules.builtin"
    test -s "$moduleDir/modules.builtin.modinfo"
    test -n "$(find "$moduleDir/kernel" -name '*.ko' -print -quit)"
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
      nftables = kernelConfig.isEnabled "NF_TABLES";
    };
    auroraSourceCommit = sourceCommit;
    auroraDtbAbi = 1;
    auroraCtxrExecmem = true;
  };

  meta = {
    description = "Verified integration kernel and modules for the Apple J773g";
    platforms = [ "x86_64-linux" "aarch64-linux" ];
    license = lib.licenses.gpl2Only;
  };
}
