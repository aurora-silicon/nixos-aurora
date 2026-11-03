# FEX from Aurora's fork in place of nixpkgs' fex: nixpkgs' recipe (thunks,
# FEXConfig, its checks) on the fork's source. The fork's submodules are
# pinned in sources.json (extra_sources) at its gitlinks.
{ lib, fex, fetchurl, runCommand, pin }:
let
  short = builtins.substring 0 7 pin.commit;
  # Submodule -> path in the tree.
  paths = {
    cpp-optparse = "Source/Common/cpp-optparse";
    drm-headers = "External/drm-headers";
    jemalloc = "External/jemalloc_glibc";
    range-v3 = "External/range-v3";
    rpmalloc = "External/rpmalloc";
    Vulkan-Headers = "External/Vulkan-Headers";
    vixl = "External/vixl";
    unordered_dense = "External/unordered_dense";
  };
  archive = name: record: fetchurl {
    name = "${name}-${record.commit}.tar.gz";
    url = record.source_url;
    hash = record.nix_hash;
  };
  src = runCommand "fex-${pin.version}-aurora-g${short}-source" { } (''
    mkdir -p $out
    tar -xzf ${archive "fex" pin} --strip-components=1 -C $out
  '' + lib.concatStrings (lib.mapAttrsToList (name: record: ''
    mkdir -p $out/${paths.${name}}
    tar -xzf ${archive name record} --strip-components=1 -C $out/${paths.${name}}
  '') pin.extra_sources));
in
assert lib.assertMsg (builtins.attrNames paths == builtins.attrNames pin.extra_sources)
  "Every pinned FEX submodule needs a path, and every path a pin";
fex.overrideAttrs (finalAttrs: old: {
  # nixpkgs' postPatch writes FEX-<version> as the describe string.
  version = "${pin.version}-aurora-g${short}";
  inherit src;
  passthru = (old.passthru or { }) // { inherit (pin) commit; };
  meta = old.meta // {
    description = "Fast usermode x86 and x86-64 emulator for Arm64 Linux (Aurora build)";
    homepage = "https://github.com/aurora-silicon/fex";
    changelog = "https://github.com/aurora-silicon/fex/commits/${pin.commit}";
  };
})
