# Content-verified, pinned SDK objects. Only this fixed-output fetch uses the
# network; the Mesa build and export run offline in a regular derivation.
{ lib, stdenvNoCC, ostree, cacert, branch, lock }:
stdenvNoCC.mkDerivation {
  name = "aurora-flatpak-sdk-${branch}";
  nativeBuildInputs = [ ostree ];
  outputHashMode = "recursive";
  outputHashAlgo = "sha256";
  outputHash = lock.nix_hash;
  impureEnvVars = lib.fetchers.proxyImpureEnvVars;
  SSL_CERT_FILE = "${cacert}/etc/ssl/certs/ca-bundle.crt";
  buildCommand = ''
    ostree init --repo="$out" --mode=archive-z2
    ostree remote add --repo="$out" --no-gpg-verify \
      --set=tls-ca-path=${cacert}/etc/ssl/certs/ca-bundle.crt flathub https://dl.flathub.org/repo
    ${lib.concatStringsSep "\n" (lib.mapAttrsToList (ref: commit: ''
      ostree pull --repo="$out" --depth=0 flathub ${lib.escapeShellArg commit}
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
