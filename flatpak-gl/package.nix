# The Flatpak ABI comes from the pinned Freedesktop SDK, not NixOS's libc.
# The manifest is adapted from the MIT-licensed recipe in
# https://github.com/aurora-silicon/fedora-aurora/tree/f96fb7aad347bc4689b28f6426090abcc3ed4115/packages/aurora-flatpak-gl
{ lib, stdenvNoCC, fetchurl, flatpak, flatpak-builder, ostree, python3, callPackage
, mesaSrc, mesaPin }:
let
  branches = [ "25.08" "26.08" ];
  locks = builtins.fromJSON (builtins.readFile ./sdk-lock.json);
  template = builtins.fromJSON (builtins.readFile ./manifest.json.in);
  sdkFor = branch: callPackage ./sdk.nix { inherit branch; lock = locks.${branch}; };
  buildBranch = branch: let
    sdk = sdkFor branch;
    manifest = template // {
      inherit branch;
      runtime-version = branch;
      modules = map (module: module // {
        sources = map (source: let
          archive = if module.name == "mesa" then mesaSrc else fetchurl {
            inherit (source) url;
            sha256 = source.sha256;
          };
        in (builtins.removeAttrs source [ "url" "dest-filename" ]) // {
          path = toString archive;
          sha256 = if module.name == "mesa" then mesaPin.sha256 else source.sha256;
        }) module.sources;
        build-options = (module.build-options or { }) // lib.optionalAttrs (module.name == "mesa") {
          env = module.build-options.env // { MESA_GIT_SHA1_OVERRIDE = mesaPin.commit; };
        };
      }) template.modules;
    };
  in stdenvNoCC.mkDerivation {
    pname = "aurora-flatpak-gl-${branch}";
    version = "${mesaPin.version}-${builtins.substring 0 12 mesaPin.commit}";
    nativeBuildInputs = [ flatpak flatpak-builder ostree python3 ];
    dontUnpack = true;
    manifestJSON = builtins.toJSON manifest;
    publicManifestJSON = builtins.replaceStrings
      [ "@BRANCH@" "@COMMIT@" "@SHA256@" ]
      [ branch mesaPin.commit mesaPin.sha256 ] (builtins.readFile ./manifest.json.in);
    passAsFile = [ "manifestJSON" "publicManifestJSON" ];
    buildPhase = ''
      runHook preBuild
      export HOME="$PWD/home" XDG_DATA_HOME="$PWD/data" XDG_CACHE_HOME="$PWD/cache"
      export XDG_RUNTIME_DIR="$PWD/runtime" FLATPAK_SYSTEM_DIR="$PWD/empty-system"
      mkdir -p "$HOME" "$XDG_RUNTIME_DIR" "$FLATPAK_SYSTEM_DIR"
      chmod 700 "$XDG_RUNTIME_DIR"
      cp -r --no-preserve=mode ${sdk} sdk-repo
      flatpak build-update-repo sdk-repo
      flatpak remote-add --user --no-gpg-verify sdk "file://$PWD/sdk-repo"
      flatpak install --user --noninteractive -y --no-deps --no-related sdk \
        ${lib.concatMapStringsSep " " lib.escapeShellArg (lib.attrNames locks.${branch}.refs)}
      cp "$manifestJSONPath" manifest.json
      flatpak-builder --arch=aarch64 --disable-rofiles-fuse --disable-download \
        --override-source-date-epoch=1 --force-clean --state-dir="$PWD/state" build manifest.json
      # Publish reproducible public source locations in the extension's
      # manifest, rather than the build-only Nix archive paths.
      install -m644 "$publicManifestJSONPath" build/files/manifest.json
      python3 - build/metadata <<'PY'
    from pathlib import Path
    import sys
    p = Path(sys.argv[1])
    text = p.read_text()
    assert '[ExtensionOf]' in text
    lines = [line for line in text.splitlines() if not line.startswith('priority=')]
    p.write_text('\n'.join(lines).replace('[ExtensionOf]', '[ExtensionOf]\npriority=10') + '\n')
    PY
      echo ${mesaPin.commit} > build/files/.aurora-mesa-commit
      runHook postBuild
    '';
    installPhase = ''
      runHook preInstall
      flatpak build-export --arch=aarch64 --timestamp=1970-01-01T00:00:01Z \
        --subject="Aurora Mesa ${mesaPin.commit} for ${branch}" "$out" build ${branch}
      echo ${mesaPin.commit} > "$out/aurora-mesa-commit.${branch}"
      runHook postInstall
    '';
  };
in stdenvNoCC.mkDerivation {
  pname = "aurora-flatpak-gl-repository";
  version = "${mesaPin.version}-${builtins.substring 0 12 mesaPin.commit}";
  nativeBuildInputs = [ ostree flatpak python3 ];
  dontUnpack = true;
  buildCommand = ''
    ostree init --repo="$out" --mode=archive-z2
    ${lib.concatMapStringsSep "\n" (branch: ''
      ostree pull-local --repo="$out" ${buildBranch branch} \
        runtime/org.freedesktop.Platform.GL.aurora/aarch64/${branch}
      cp ${buildBranch branch}/aurora-mesa-commit.${branch} "$out/"
    '') branches}
    flatpak build-update-repo "$out"
    python3 ${./validate-repository.py} --repo "$out" --commit ${mesaPin.commit}
  '';
  passthru = {
    inherit branches;
    inherit (mesaPin) commit;
    sdks = lib.genAttrs branches sdkFor;
  };
  meta = {
    description = "Aurora Mesa for the 25.08 and 26.08 Flatpak runtimes";
    homepage = "https://github.com/aurora-silicon/nixos-aurora";
    license = lib.licenses.mit;
    platforms = [ "aarch64-linux" ];
  };
}
