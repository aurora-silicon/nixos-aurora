# Content-verified, pinned SDK objects. Only this fixed-output fetch uses the
# network; the Mesa build and export run offline in a regular derivation.
{ lib, stdenvNoCC, ostree, curl, cacert, branch, lock }:
stdenvNoCC.mkDerivation {
  name = "aurora-flatpak-sdk-${branch}";
  nativeBuildInputs = [ ostree curl ];
  outputHashMode = "recursive";
  outputHashAlgo = "sha256";
  outputHash = lock.nix_hash;
  impureEnvVars = lib.fetchers.proxyImpureEnvVars;
  SSL_CERT_FILE = "${cacert}/etc/ssl/certs/ca-bundle.crt";
  buildCommand = ''
    ostree init --repo="$out" --mode=archive-z2
    ostree remote add --repo="$out" --no-gpg-verify \
      --set=tls-ca-path=${cacert}/etc/ssl/certs/ca-bundle.crt --set=http2=false \
      flathub https://dl.flathub.org/repo
    ${lib.concatStringsSep "\n" (lib.mapAttrsToList (ref: commit: ''
      if ! ostree pull --repo="$out" --depth=0 flathub ${lib.escapeShellArg commit}; then
        echo 'SDK metadata fetch failed; public endpoint HTTP diagnostics:' >&2
        curl --head --max-time 30 --cacert ${cacert}/etc/ssl/certs/ca-bundle.crt \
          https://dl.flathub.org/repo/objects/${builtins.substring 0 2 commit}/${builtins.substring 2 62 commit}.commit || true
        exit 1
      fi
      ostree refs --repo="$out" --create=${lib.escapeShellArg ref} ${lib.escapeShellArg commit}
    '') lock.refs)}
    ostree remote delete --repo="$out" flathub
    # Detached signatures may be refreshed independently of the immutable
    # commit. Object checksums provide this fetch's content verification.
    find "$out/objects" -type f -name '*.commitmeta' -delete
    rm -rf "$out/tmp" "$out/state" "$out/refs/remotes" "$out/repo.lock"
    mkdir -p "$out/tmp" "$out/state" "$out/refs/remotes"
  '';
}
