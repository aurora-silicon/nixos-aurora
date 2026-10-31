# CPU Vulkan uses LLVM separately from the native GL/Honeykrisp closure.
{ callPackage, lib, mesa, src, commit, vulkan-tools }:
(callPackage ./mesa.nix { inherit mesa src commit; }).overrideAttrs (old: {
  pname = "mesa-aurora-lavapipe";
  outputs = [ "out" ];
  mesonFlags = (lib.filter (flag:
    !(lib.hasPrefix "-Dvulkan-drivers=" flag || lib.hasPrefix "-Dgallium-drivers=" flag)) old.mesonFlags)
    ++ [ "-Dvulkan-drivers=swrast" "-Dgallium-drivers=softpipe" ];
  configurePhase = ''
    runHook preConfigure
    meson setup tools --prefix="$out" --libdir=lib --buildtype=release "''${mesonFlags[@]}" \
      -Dllvm=enabled -Dbuild-tests=false
    runHook postConfigure
  '';
  buildPhase = ''
    ninja -C tools -j "$NIX_BUILD_CORES" src/gallium/targets/lavapipe/libvulkan_lvp.so \
      src/gallium/targets/lavapipe/lvp_icd.aarch64.json
  '';
  doCheck = false;
  installPhase = ''
    install -Dm755 tools/src/gallium/targets/lavapipe/libvulkan_lvp.so "$out/lib/libvulkan_lvp.so"
    install -Dm644 tools/src/gallium/targets/lavapipe/lvp_icd.aarch64.json \
      "$out/share/vulkan/icd.d/lvp_icd.aarch64.json"
    echo ${commit} > "$out/.aurora-mesa-commit"
  '';
  postInstall = "";
  postFixup = ''
    test -f "$out/lib/libvulkan_lvp.so"
    grep -F "\"library_path\": \"$out/lib/libvulkan_lvp.so\"" "$out/share/vulkan/icd.d/lvp_icd.aarch64.json"
    readelf -h "$out/lib/libvulkan_lvp.so" | grep 'Machine:.*AArch64'
    # Load the installed ICD and enumerate a real CPU Vulkan device in CI.
    export XDG_RUNTIME_DIR="$TMPDIR"
    VK_DRIVER_FILES="$out/share/vulkan/icd.d/lvp_icd.aarch64.json" \
      ${vulkan-tools}/bin/vulkaninfo --summary > lavapipe-summary.txt
    grep -i llvmpipe lavapipe-summary.txt
  '';
  disallowedRequisites = [ ];
})
