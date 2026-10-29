{ lib, mesa, src, vulkan-loader, llvmPackages, spirv-tools
, commit, guest ? false, compilerTools ? null }:
(mesa.override { stdenv = llvmPackages.stdenv; }).overrideAttrs (old: {
  inherit src;
  version = "26.3.0";
  env = (old.env or { }) // { MESA_GIT_SHA1_OVERRIDE = commit; };
  patches = [ ];
  outputs = [ "out" ];
  mesonAutoFeatures = "auto";
  # Nix splits Clang's library output from LLVM's library directory.
  postPatch = (old.postPatch or "") + ''
    substituteInPlace meson.build --replace-fail 'dirs : llvm_libdir' \
      "dirs : [llvm_libdir, '${lib.getLib llvmPackages.clang-unwrapped}/lib']"
  '';
  preConfigure = (old.preConfigure or "") + ''
    export CC=${llvmPackages.clang}/bin/clang
    export CXX=${llvmPackages.clang}/bin/clang++
    export CC_FOR_BUILD="$CC"
    export CXX_FOR_BUILD="$CXX"
    "$CC" --version
  '';
  mesonBuildType = "release";
  mesonFlags = [
    "-Dplatforms=x11,wayland" "-Dgallium-drivers=asahi,zink,softpipe"
    "-Dvulkan-drivers=asahi" "-Dvulkan-layers=" "-Dglvnd=enabled"
    "-Degl=enabled" "-Dgbm=enabled" "-Dglx=dri" "-Dgles1=enabled"
    "-Dgles2=enabled" "-Dvideo-codecs=${if guest then "" else "all"}" "-Dexpat=enabled"
    "-Dzstd=enabled" "-Dlmsensors=${if guest then "disabled" else "enabled"}" "-Dlibunwind=disabled"
    "-Dvalgrind=disabled" "-Db_ndebug=true" "-Dwrap_mode=nodownload"
  ];
  configurePhase = ''
    runHook preConfigure
  '' + lib.optionalString (compilerTools == null) ''
    meson setup tools --prefix="$out" --libdir=lib --buildtype=release "''${mesonFlags[@]}" \
      -Dllvm=enabled -Dbuild-tests=false
    meson introspect tools --compilers | python3 -c '
import json,sys
assert json.load(sys.stdin)["host"]["c"]["id"] == "clang", "Mesa must use the selected Clang toolchain"
'
    ninja -C tools -j "$NIX_BUILD_CORES" src/compiler/clc/mesa_clc \
      src/compiler/spirv/vtn_bindgen2 src/asahi/clc/asahi_clc
    printf "[binaries]\nmesa_clc = '%s'\nvtn_bindgen2 = '%s'\nasahi_clc = '%s'\n" \
      "$PWD/tools/src/compiler/clc/mesa_clc" "$PWD/tools/src/compiler/spirv/vtn_bindgen2" \
      "$PWD/tools/src/asahi/clc/asahi_clc" > tools.ini
  '' + lib.optionalString (compilerTools != null) ''
    printf "[binaries]\nmesa_clc = '%s/bin/mesa_clc'\nvtn_bindgen2 = '%s/bin/vtn_bindgen2'\nasahi_clc = '%s/bin/asahi_clc'\n" \
      ${compilerTools} ${compilerTools} ${compilerTools} > tools.ini
  '' + ''
    meson setup build --prefix=${if guest then "/usr" else "\"$out\""} \
      --libdir=${if guest && llvmPackages.stdenv.hostPlatform.is64bit then "lib64" else "lib"} \
      --buildtype=release "''${mesonFlags[@]}" \
      --native-file tools.ini -Dllvm=disabled -Dspirv-tools=disabled \
      -Dmesa-clc=system -Dprecomp-compiler=system -Dbuild-tests=true
    runHook postConfigure
    cd build
  '';
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    meson test --print-errorlogs --num-processes "$NIX_BUILD_CORES"
    runHook postCheck
  '';
  postInstall = "";
  # Guest libraries run inside a distribution rootfs, so they use its loaders
  # and dependencies, never the host's Nix store or release-specific LLVM.
  installPhase = if guest then ''
    runHook preInstall
    DESTDIR="$out" meson install --no-rebuild
    runHook postInstall
  '' else (old.installPhase or ''
    runHook preInstall
    ninja install
    runHook postInstall
  '');
  postFixup = if guest then ''
    find "$out" -type f -name '*.so*' -exec patchelf --remove-rpath {} +
    rm -rf "$out/usr/include" "$out/usr/lib/pkgconfig" "$out/usr/lib64/pkgconfig"
    echo ${commit} > "$out/.aurora-mesa-commit"
    if find "$out" -type f -name '*.so*' -exec readelf -d {} + | \
      grep -E 'NEEDED.*(libLLVM|libSPIRV-Tools|libsensors|libunwind)|/nix/store'; then
      echo 'guest Mesa retains a host or release-specific dependency' >&2
      exit 1
    fi
  '' else ''
    for js in "$out"/share/glvnd/egl_vendor.d/*.json; do
      substituteInPlace "$js" --replace-fail '"libEGL_' '"'"$out/lib/libEGL_"
    done
    python3 - "$out" <<'PYFIX'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
for path in (root / "share/vulkan/icd.d").glob("*.json"):
    data = json.loads(path.read_text())
    name = pathlib.Path(data["ICD"]["library_path"]).name
    assert name == "libvulkan_asahi.so", name
    library = root / "lib" / name
    assert library.is_file(), library
    data["ICD"]["library_path"] = str(library)
    path.write_text(json.dumps(data, indent=2) + "\n")
PYFIX
    patchelf --add-rpath ${vulkan-loader}/lib "$out"/lib/libgallium*.so
  '';
  disallowedRequisites = [ llvmPackages.libllvm spirv-tools ];
  allowedReferences = if guest then [ "out" ] else null;
})
