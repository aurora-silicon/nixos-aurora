{ lib, m1n1, rustPlatform, llvmPackages, buildPackages, src, pin, auraMonitorFree }:
(m1n1.override { customLogo = null; }).overrideAttrs (old:
let customLogo = lib.elem "LOGO=custom" old.makeFlags;
in {
  pname = "aura";
  inherit (pin) version;
  inherit src;
  passthru = (old.passthru or { }) // { inherit auraMonitorFree; };
  cargoDeps = rustPlatform.importCargoLock {
    lockFile = ../locks/aura.Cargo.lock;
    outputHashes."fatfs-0.4.0" = "sha256-r1STNZupll2U5MppT0gNmEKDl9gevRTYZFOAVimtZxU=";
  };
  # Keep the upstream customLogo override API, but link Aura's three raw
  # built-in sizes instead of appending m1n1's two-size logo payload.
  postPatch = lib.optionalString customLogo (old.postPatch + ''
    for size in 48 128 256; do
      magick data/custom_256.png -background black -alpha remove -alpha off \
        -resize "''${size}x''${size}" -gravity center -extent "''${size}x''${size}" \
        -depth 8 "rgba:data/custom_''${size}.bin"
      test "$(wc -c < data/custom_''${size}.bin)" -eq "$((size * size * 4))"
    done
  '');
  # Build with clang and lld, as Fedora and Arch do. With GCC, aura's image
  # outgrows the space that aura-raw.ld leaves before the DCP log buffer.
  # python3 runs the build's built-in logo check.
  nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [
    llvmPackages.clang-unwrapped llvmPackages.lld llvmPackages.llvm buildPackages.python3
  ];
  makeFlags = [ "RELEASE=1" "CHAINLOADING=1" "BUILTIN_LOGO=${if customLogo then "custom" else "aurora"}" "USE_CLANG=1" ];
  # Archive builds need the release label only while the source pin names it.
  env = (old.env or { }) // lib.optionalAttrs (pin ? release_tag) {
    AURA_VERSION_TAG = pin.release_tag;
  };
  postBuild = ''
    mkdir -p stage1
    cp build/aura.bin stage1/aura-raw.bin
    cp build/aura.macho stage1/aura.macho
    cp build/aura-boot.macho stage1/aura-boot.macho
    make clean
    # The secure-flavour Stage 1 that aurora-secboot stage1 build fills with the
    # owner's key. Its built-in key, used only while the key block is unfilled, is
    # a fresh one whose private half is never written down, so an unfilled image
    # verifies nothing. The key stays out of $out.
    python3 -c 'import os, sys; sys.path.insert(0, "tools"); import secboot_sign; sys.stdout.buffer.write(secboot_sign.pubkey(os.urandom(32)))' > "$TMPDIR/nobody.pub"
    make $makeFlags SECBOOT=audit SECBOOT_FLAVOUR=secure SECBOOT_PUBKEY="$TMPDIR/nobody.pub"
    cp build/aura.bin stage1/aura-secure-raw.bin
    make clean
    make $makeFlags ESP_STAGE2=1
  '';
  installPhase = ''
    mkdir -p $out/lib/m1n1 $out/share/aura/stage1
    cp build/aura.bin $out/lib/m1n1/m1n1.bin
    cp stage1/* $out/share/aura/stage1/
    # aura's own Stage 1 and signing tools, for aurora-secboot stage1 build and
    # its stage2 hook (AURORA_SECBOOT_AURA_DIR=$out/share/aura).
    install -Dm644 -t $out/share/aura/tools \
      tools/fill_stage1_config.py tools/secboot_sign.py tools/macho_boot_object.py \
      tools/recovery/enroll-stage1.sh
    # Monitor-free Aura makes Stage 2 stop updating boot.bin on Mach-O Macs.
    found=false
    if [ -f src/ctxr_exec.c ] || [ ! -f src/monitor.c ]; then found=true; fi
    if [ "$found" != ${lib.boolToString auraMonitorFree} ]; then
      echo "overlay.nix: set auraMonitorFree = $found; which the pinned source is" >&2
      exit 1
    fi
    ${lib.optionalString auraMonitorFree "touch $out/share/aura/monitor-free"}
  '';
  doCheck = false; # Upstream m1n1's Python suite is not the Aura test suite.
  meta = old.meta // {
    description = "Aura bootloader for Apple Silicon";
    homepage = "https://github.com/aurora-silicon/aura";
    longDescription = ''
      Aurora's bootloader, with Stage 1 and ESP Stage 2 outputs. It links the
      Aurora logo by default. Set customLogo to an image to replace it at all
      three built-in sizes; null retains the Aurora logo.
    '';
  };
})
