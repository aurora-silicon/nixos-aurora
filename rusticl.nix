# Rusticl alone uses the compiler runtime, from the same pin as native Mesa.
{ callPackage, lib, mesa, src, commit, vulkan-loader }:
(callPackage ./mesa.nix { inherit mesa src commit; }).overrideAttrs (old: {
  pname = "mesa-aurora-rusticl";
  outputs = [ "out" ];
  mesonFlags = (lib.filter (flag: flag != "-Dgallium-rusticl=false") old.mesonFlags)
    ++ [ "-Dgallium-rusticl=true" ];
  configurePhase = ''
    runHook preConfigure
    meson setup tools --prefix="$out" --libdir=lib --buildtype=release "''${mesonFlags[@]}" \
      -Dllvm=enabled -Dspirv-tools=enabled -Dbuild-tests=false
    runHook postConfigure
  '';
  buildPhase = ''
    ninja -C tools -j "$NIX_BUILD_CORES" src/gallium/targets/rusticl/libRusticlOpenCL.so.1.0.0
  '';
  doCheck = false;
  installPhase = ''
    runHook preInstall
    install -Dm755 tools/src/gallium/targets/rusticl/libRusticlOpenCL.so.1.0.0 \
      "$out/lib/libRusticlOpenCL.so.1.0.0"
    ln -s libRusticlOpenCL.so.1.0.0 "$out/lib/libRusticlOpenCL.so.1"
    ln -s libRusticlOpenCL.so.1 "$out/lib/libRusticlOpenCL.so"
    mkdir -p "$out/etc/OpenCL/vendors"
    echo "$out/lib/libRusticlOpenCL.so" > "$out/etc/OpenCL/vendors/rusticl.icd"
    echo ${commit} > "$out/.aurora-mesa-commit"
    runHook postInstall
  '';
  postInstall = "";
  postFixup = ''
    patchelf --add-rpath ${vulkan-loader}/lib "$out/lib/libRusticlOpenCL.so.1.0.0"
    test -f "$(cat "$out/etc/OpenCL/vendors/rusticl.icd")"
    readelf -h "$out/lib/libRusticlOpenCL.so.1.0.0" | grep 'Machine:.*AArch64'
    readelf -Ws "$out/lib/libRusticlOpenCL.so.1.0.0" | grep 'clGetPlatformIDs'
  '';
  disallowedRequisites = [ ];
})
