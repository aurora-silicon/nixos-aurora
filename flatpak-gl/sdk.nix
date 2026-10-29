# Only this fixed-output fetch uses the network. The Mesa build is offline.
{ lib, stdenvNoCC, ostree, curl, python3, cacert, branch, lock }:
stdenvNoCC.mkDerivation {
  name = "aurora-flatpak-sdk-${branch}";
  nativeBuildInputs = [ ostree curl python3 ];
  outputHashMode = "recursive";
  outputHashAlgo = "sha256";
  outputHash = lock.nix_hash;
  impureEnvVars = lib.fetchers.proxyImpureEnvVars;
  refsJSON = builtins.toJSON lock.refs;
  passAsFile = [ "refsJSON" ];
  buildCommand = ''
    export XDG_CONFIG_HOME="$TMPDIR/sdk-config" XDG_CACHE_HOME="$TMPDIR/sdk-cache"
    mkdir -p "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME"
    ostree init --repo="$out" --mode=archive-z2
    python3 ${./fetch-sdk.py} --repo "$out" --refs "$refsJSONPath" \
      --ca-file ${cacert}/etc/ssl/certs/ca-bundle.crt
    # Detached signatures can change independently of the immutable commit.
    # Its content graph and the fixed-output hash verify this fetch.
    find "$out/objects" -type f -name '*.commitmeta' -delete
    rm -rf "$out/tmp" "$out/state" "$out/refs/remotes" "$out/repo.lock"
    mkdir -p "$out/tmp" "$out/state" "$out/refs/remotes"
  '';
}
