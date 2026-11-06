# Native x86 shader tools are shared by both guest driver architectures.
{ callPackage, src, version, commit }:
(callPackage ./mesa-common.nix { inherit src version commit; }).overrideAttrs (_: {
  pname = "aurora-mesa-compiler-tools";
  configurePhase = ''
    runHook preConfigure
    meson setup tools --prefix="$out" --libdir=lib --buildtype=release "''${mesonFlags[@]}" \
      -Dllvm=enabled -Dbuild-tests=false
  '';
  buildPhase = ''
    ninja -C tools -j "$NIX_BUILD_CORES" src/compiler/clc/mesa_clc \
      src/compiler/spirv/vtn_bindgen2 src/asahi/clc/asahi_clc
  '';
  doCheck = false;
  installPhase = ''
    mkdir -p $out/bin
    cp tools/src/compiler/clc/mesa_clc tools/src/compiler/spirv/vtn_bindgen2 \
      tools/src/asahi/clc/asahi_clc $out/bin/
  '';
  postFixup = "";
  postInstall = "";
})
