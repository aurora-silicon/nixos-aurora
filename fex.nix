# FEX from Aurora's fork in place of nixpkgs' fex: nixpkgs' recipe (thunks,
# FEXConfig, its checks) on the fork's source. The fork's submodules are
# pinned in sources.json (extra_sources) at its gitlinks.
{ lib, fex, fetchurl, runCommand, pin }:
let
  short = builtins.substring 0 7 pin.commit;
  # Source tracking records and verifies each gitlink alongside its path.
  requiredSubmodules = [ "Vulkan-Headers" "cpp-optparse" "drm-headers" "jemalloc"
    "range-v3" "rpmalloc" "unordered_dense" "vixl" ];
  archive = name: record: fetchurl {
    name = "${name}-${record.commit}.tar.gz";
    url = record.source_url;
    hash = record.nix_hash;
  };
  src = runCommand "fex-${pin.version}-aurora-g${short}-source" { } (''
    mkdir -p $out
    tar -xzf ${archive "fex" pin} --strip-components=1 -C $out
  '' + lib.concatStrings (lib.mapAttrsToList (name: record: ''
    mkdir -p $out/${record.path}
    tar -xzf ${archive name record} --strip-components=1 -C $out/${record.path}
  '') pin.extra_sources));
in
assert lib.assertMsg ((pin.submodules_commit or null) == pin.commit)
  "Refresh every FEX submodule pin with the parent commit";
assert lib.assertMsg (requiredSubmodules == builtins.attrNames pin.extra_sources)
  "Every pinned FEX submodule needs a path, and every path a pin";
fex.overrideAttrs (_finalAttrs: old: {
  # nixpkgs' postPatch writes FEX-<version> as the describe string.
  version = "${pin.version}-aurora-g${short}";
  inherit src;
  # FEX tunes for the build machine by default (-mcpu from its /proc/cpuinfo),
  # which crashes with SIGILL on Apple CPUs when CI builds on Neoverse.
  cmakeFlags = old.cmakeFlags ++ [ (lib.cmakeFeature "TUNE_CPU" "none") ];
  passthru = (old.passthru or { }) // { inherit (pin) commit; };
  meta = old.meta // {
    description = "Fast usermode x86 and x86-64 emulator for Arm64 Linux (Aurora build)";
    homepage = "https://github.com/aurora-silicon/fex";
    changelog = "https://github.com/aurora-silicon/fex/commits/${pin.commit}";
  };
})
