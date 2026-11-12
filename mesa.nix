{ callPackage, lib, mesa, src, version, vulkan-loader, llvmPackages, spirv-tools, stdenv
, mesa-libclc, spirv-llvm-translator, lm_sensors, libunwind
, rustc, rust-bindgen, rust-cbindgen, valgrind-light
, commit, guest ? false, compilerTools ? null }:
(callPackage ./pkgs/mesa-common.nix {
  inherit lib mesa src version llvmPackages spirv-tools stdenv mesa-libclc
    spirv-llvm-translator lm_sensors libunwind rustc rust-bindgen rust-cbindgen
    valgrind-light commit guest;
}).overrideAttrs (old: {
  outputs = [ "out" ] ++ lib.optionals (!guest) [ "dev" ];
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
  postInstall = ''
    # Assert the installed artifact, including after Meson test regeneration.
    strings "$out/${if guest then "usr/${if llvmPackages.stdenv.hostPlatform.is64bit then "lib64" else "lib"}" else "lib"}/libvulkan_asahi.so" | \
      grep -F '(git-${builtins.substring 0 10 commit}), Borealis'
    echo ${commit} > "$out/.aurora-mesa-commit"
  '';
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
    # Removing an RPATH tag alone leaves its old .dynstr bytes behind.
    # Empty it first so neither the loader nor Nix retains host paths.
    find "$out" -type f -name '*.so*' -exec patchelf --set-rpath "" {} +
    find "$out" -type f -name '*.so*' -exec patchelf --remove-rpath {} +
    rm -rf "$out/usr/include" "$out/usr/lib/pkgconfig" "$out/usr/lib64/pkgconfig"
    echo ${commit} > "$out/.aurora-mesa-commit"
    if find "$out" -type f -name '*.so*' -exec readelf -d {} + | \
      grep -E '\(NEEDED\).*(libLLVM|libSPIRV-Tools|libsensors|libunwind|/nix/store)|\((RPATH|RUNPATH)\).*/nix/store'; then
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
