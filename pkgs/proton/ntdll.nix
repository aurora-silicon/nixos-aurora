# Reproduce the exact Wine preparation for the GE release; see README.md.
{
  stdenv,
  fetchurl,
  autoconf,
  bison,
  flex,
  perl,
  python3,
  pkg-config,
  patchelf,
  clang-unwrapped,
  lld,
  llvm,
  util-linux,
}:
let
  pin = builtins.fromJSON (builtins.readFile ./sources.json);
  source = name: fetchurl pin.archives.${name};
  vkXml = source "vk-xml";
  videoXml = source "video-xml";
  geSource = source "ge-source";
  wineStaging = source "wine-staging";
  restoreConfigure = source "restore-configure";
in
stdenv.mkDerivation {
  pname = "aurora-proton-sme-ntdll";
  inherit (pin) version;
  src = source "wine";
  nativeBuildInputs = [ autoconf bison flex perl python3 pkg-config patchelf clang-unwrapped lld llvm util-linux ];
  configurePhase = ''
    runHook preConfigure
    export XDG_CACHE_HOME="$TMPDIR/cache"
    # Reproduce GE's own Wine preparation before applying the SME fix.
    # Its Wine submodule alone omits Wine-Staging and GE's patch series.
    originalWineSource="$PWD"
    mkdir -p "$TMPDIR/ge/wine-staging"
    tar -xf ${geSource} -C "$TMPDIR/ge" --strip-components=1
    tar -xf ${wineStaging} -C "$TMPDIR/ge/wine-staging" --strip-components=1
    rmdir "$TMPDIR/ge/wine" 2>/dev/null || true
    mv "$originalWineSource" "$TMPDIR/ge/wine"
    wineSource="$TMPDIR/ge/wine"
    cd "$wineSource"
    # Wine-Staging's gitapply uses a bare + in an awk regexp; newer gawk
    # rejects it. The character class preserves the intended literal match.
    substituteInPlace "$TMPDIR/ge/wine-staging/patches/gitapply.sh" --replace-fail '|+|-' '|[+]|-'
    patchShebangs tools dlls/winevulkan "$TMPDIR/ge/wine-staging/staging" "$TMPDIR/ge/wine-staging/patches"
    (cd "$TMPDIR/ge/wineopenxr" && patch -Np1 < ../patches/wineopenxr/wineopenxr_decouple.patch)
    {
      head -n 14 "$TMPDIR/ge/patches/protonprep-valve-staging.sh"
      sed -n '/^### (2) WINE PATCHING ###/,/^### END WINE PATCHING ###/p' "$TMPDIR/ge/patches/protonprep-valve-staging.sh" |
        sed -e '/^[[:space:]]*git reset --hard HEAD/d' \
            -e '/^[[:space:]]*git clean -xdf/d' \
            -e 's|git revert --no-commit e813ca5771658b00875924ab88d525322e50d39f|patch -Rp1 < ${restoreConfigure}|'
    } > "$TMPDIR/ge/prepare-wine.sh"
    (cd "$TMPDIR/ge" && bash -e prepare-wine.sh)
    cd "$wineSource"
    patch -Np1 < ${./wine-sve-guard.patch}
    perl tools/make_requests
    perl tools/make_specfiles
    (cd dlls/winevulkan && python3 make_vulkan -x ${vkXml} -X ${videoXml})
    autoreconf -if
    mkdir build
    cd build
    ../configure --enable-archs=aarch64 --disable-tests --without-x --without-freetype --without-fontconfig
    runHook postConfigure
  '';
  buildPhase = ''
    runHook preBuild
    make -j "$NIX_BUILD_CORES" dlls/ntdll/ntdll.so
    runHook postBuild
  '';
  installPhase = ''
    mkdir -p "$out/lib"
    cp dlls/ntdll/ntdll.so "$out/lib/ntdll.so"
    patchelf --remove-rpath "$out/lib/ntdll.so"
  '';
  dontStrip = true;
}
