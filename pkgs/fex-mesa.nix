{ runCommand, binutils, pin, mesa64, mesa32 }:
runCommand "aurora-fex-mesa-${pin.version}-${builtins.substring 0 12 pin.commit}" {
  nativeBuildInputs = [ binutils ];
  passthru = { inherit (pin) commit; };
} ''
  mkdir -p $out/usr
  cp -a ${mesa64}/usr/lib64 $out/usr/
  cp -a ${mesa32}/usr/lib $out/usr/
  cp -a ${mesa64}/usr/share $out/usr/
  # The manifest directory is shared by both guest architectures.
  chmod -R u+w $out/usr/share
  cp -a --update=none ${mesa32}/usr/share/. $out/usr/share/
  echo ${pin.commit} > $out/.aurora-mesa-commit
  for library in $out/usr/lib64/libgallium*.so $out/usr/lib64/libvulkan_asahi.so; do
    readelf -h "$library" | grep -q 'Advanced Micro Devices X86-64'
    readelf -n "$library" | grep -Eq 'Build ID: [0-9a-f]{40}'
  done
  for library in $out/usr/lib/libgallium*.so $out/usr/lib/libvulkan_asahi.so; do
    readelf -h "$library" | grep -q 'Intel 80386'
    readelf -n "$library" | grep -Eq 'Build ID: [0-9a-f]{40}'
  done
''
