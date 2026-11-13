{ lib, stdenvNoCC, kmod, kernelPayload ? ./j773g-kernel/run59
, kernelRelease ? "7.3.0-m4atlrx+"
, sourceCommit ? "b3218010d34be05fa0d6ebfb6fd08638ecdb7451"
, imageSha256 ? "13d3d96630b2cb68c5d3828819431fe5b4c851a4f40c0b498978ead27fe662e7"
, dtbSha256 ? "5a72db650a379a3320d2736be69a152c5836e16a3cb038a50f0d692180620e46"
}:

let
  configText = builtins.readFile (kernelPayload + "/config");
  kernelConfig = rec {
    isYes = name: lib.hasInfix "\nCONFIG_${name}=y\n" "\n${configText}\n";
    isNo = name: lib.hasInfix "\n# CONFIG_${name} is not set\n" "\n${configText}\n";
    isModule = name: lib.hasInfix "\nCONFIG_${name}=m\n" "\n${configText}\n";
    isSet = name: isYes name || isNo name || isModule name;
    getValue = name: if isYes name then "y" else if isModule name then "m" else if isNo name then "n" else null;
    isEnabled = name: isYes name || isModule name;
    isDisabled = name: !isEnabled name;
  };
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
      nftables = kernelConfig.isEnabled "NF_TABLES";
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
