{ lib, stdenv, fetchurl, pkg-config, meson, ninja, python3, linuxHeaders, binutils, removeReferencesTo
, libdrm, systemd, libva, libplacebo, libglvnd, libgbm, wayland, wayland-protocols, wayland-scanner
, libxkbcommon, libdisplay-info, lcms2, libass, luajit, zlib, gnutls, dav1d
, libpulseaudio, alsa-lib
}:
let
  pins = (builtins.fromJSON (builtins.readFile ../sources.json)).ffmpeg-avd;
  source = pin: fetchurl {
    name = pin.archive_file or "mpv-${pin.commit}.tar.gz";
    url = pin.source_url; sha256 = pin.sha256;
  };
  stableFile = path: builtins.toFile (builtins.baseNameOf path) (builtins.readFile path);
  ffmpeg-avd = stdenv.mkDerivation {
    pname = "ffmpeg-avd";
    version = pins.version;
    outputs = [ "out" "dev" ];
    configurePlatforms = [ ];
    setOutputFlags = false;
    src = source pins;
    patches = [ (stableFile ./0001-v4l2request-n8.1.patch) ];
    strictDeps = true;
    nativeBuildInputs = [ pkg-config removeReferencesTo ];
    buildInputs = [ linuxHeaders libdrm systemd libva gnutls dav1d zlib ];
    enableParallelBuilding = true;
    configureFlags = [
      ''--libdir=${placeholder "out"}/lib/aurora-avd'' ''--incdir=${placeholder "dev"}/include/aurora-avd''
      ''--datadir=${placeholder "out"}/share/aurora-avd/ffmpeg''
      "--disable-static" "--enable-shared" "--enable-pic" "--disable-stripping"
      "--disable-debug" "--disable-doc" "--disable-ffplay" "--disable-autodetect"
      "--enable-v4l2-request" "--enable-libdrm" "--enable-libudev" "--enable-vaapi"
      "--enable-gnutls" "--enable-libdav1d" "--enable-zlib"
    ];
    preConfigure = ''
      configureFlagsArray+=("--extra-ldflags=-Wl,-rpath,$out/lib/aurora-avd")
    '';
    # FFmpeg embeds configure flags in config.h; the runtime output must not
    # refer back to the development output whose pkg-config files refer to it.
    postConfigure = ''
      remove-references-to -t "$dev" config.h
    '';
    doCheck = true;
    checkPhase = ''
      runHook preCheck
      LD_LIBRARY_PATH="$PWD/libavcodec:$PWD/libavdevice:$PWD/libavfilter:$PWD/libavformat:$PWD/libavutil:$PWD/libswresample:$PWD/libswscale" \
        ./ffmpeg -hide_banner -hwaccels > hwaccels.txt
      cat hwaccels.txt
      grep -qx v4l2request hwaccels.txt
      for codec in H264 HEVC VP9 AV1; do
        grep -q "#define CONFIG_''${codec}_V4L2REQUEST_HWACCEL 1" config_components.h
      done
      runHook postCheck
    '';
    postInstall = ''
      mv "$out/bin/ffmpeg" "$out/bin/ffmpeg-avd"
      mv "$out/bin/ffprobe" "$out/bin/ffprobe-avd"
      mkdir -p "$dev/lib/pkgconfig" "$out/share/licenses/ffmpeg-avd"
      mv "$out/lib/aurora-avd/pkgconfig/"*.pc "$dev/lib/pkgconfig/"
      rmdir "$out/lib/aurora-avd/pkgconfig"
      cp COPYING.LGPLv2.1 "$out/share/licenses/ffmpeg-avd/"
    '';
    doInstallCheck = true;
    nativeInstallCheckInputs = [ stdenv.cc.libc.bin binutils ];
    installCheckPhase = ''
      runHook preInstallCheck
      for binary in "$out"/bin/*; do
        readelf -h "$binary" > elf.txt
        cat elf.txt
        grep -q AArch64 elf.txt
        ldd "$binary" > linked.txt
        cat linked.txt
        if grep -q 'not found' linked.txt; then exit 1; fi
        grep -E 'lib(avcodec|avdevice|avfilter|avformat|avutil|swresample|swscale)\.so' linked.txt > ffmpeg-linked.txt
        test -s ffmpeg-linked.txt
        if grep -v " => $out/lib/aurora-avd/" ffmpeg-linked.txt; then
          echo 'FFmpeg dependency escaped the private library directory' >&2
          exit 1
        fi
      done
      runHook postInstallCheck
    '';
    meta = {
      description = "Private FFmpeg with the public V4L2 Request API series";
      homepage = "https://github.com/Kwiboo/FFmpeg";
      license = lib.licenses.lgpl21Plus;
      platforms = [ "aarch64-linux" ];
      mainProgram = "ffmpeg-avd";
    };
  };
  mpv-avd = stdenv.mkDerivation {
    pname = "mpv-avd";
    version = "${pins.extra_sources.mpv.version}-${builtins.substring 0 8 pins.extra_sources.mpv.commit}";
    src = source pins.extra_sources.mpv;
    patches = [ (stableFile ./0002-mpv-request-drm-import.patch) ];
    strictDeps = true;
    nativeBuildInputs = [ pkg-config meson ninja python3 wayland-scanner ];
    # TOOLS/*.py run at build time through /usr/bin/env, which the sandbox lacks.
    postPatch = ''
      patchShebangs --build TOOLS
    '';
    buildInputs = [ ffmpeg-avd libdrm systemd libva libplacebo libglvnd libgbm wayland
      wayland-protocols libxkbcommon libdisplay-info lcms2 libass luajit zlib
      gnutls dav1d libpulseaudio alsa-lib ];
    mesonAutoFeatures = "disabled";
    mesonWrapMode = "nodownload";
    mesonFlags = [ "-Dlibmpv=false" "-Dmanpage-build=disabled"
      "-Dvaapi=enabled" "-Ddrm=enabled" "-Dwayland=enabled" "-Dgl=enabled" "-Degl=enabled" "-Degl-wayland=enabled"
      "-Dgbm=enabled" "-Degl-drm=enabled" "-Ddmabuf-wayland=enabled" "-Dvaapi-drm=enabled"
      "-Dalsa=enabled" "-Dpulse=enabled" "-Dlua=luajit" "-Dlcms2=enabled" "-Dzlib=enabled"
      "-Dc_link_args=-Wl,-rpath,${ffmpeg-avd}/lib/aurora-avd" ];
    doCheck = true;
    checkPhase = ''
      runHook preCheck
      ./mpv --no-config --hwdec=help > mpv-hwdec.txt
      cat mpv-hwdec.txt
      grep -qw v4l2request mpv-hwdec.txt
      grep -qw v4l2request-copy mpv-hwdec.txt
      runHook postCheck
    '';
    installPhase = ''
      runHook preInstall
      DESTDIR="$TMPDIR/mpv-stage" meson install --no-rebuild
      install -Dm755 "$TMPDIR/mpv-stage$out/bin/mpv" "$out/bin/mpv-avd"
      install -Dm644 ../Copyright "$out/share/licenses/mpv-avd/Copyright"
      install -Dm644 ../LICENSE.GPL "$out/share/licenses/mpv-avd/LICENSE.GPL"
      runHook postInstall
    '';
    doInstallCheck = true;
    nativeInstallCheckInputs = [ stdenv.cc.libc.bin binutils ];
    installCheckPhase = ''
      runHook preInstallCheck
      for binary in "$out"/bin/*; do
        readelf -h "$binary" > elf.txt
        cat elf.txt
        grep -q AArch64 elf.txt
        ldd "$binary" > linked.txt
        cat linked.txt
        if grep -q 'not found' linked.txt; then exit 1; fi
        grep -E 'lib(avcodec|avdevice|avfilter|avformat|avutil|swresample|swscale)\.so' linked.txt > ffmpeg-linked.txt
        test -s ffmpeg-linked.txt
        if grep -v ' => ${ffmpeg-avd}/lib/aurora-avd/' ffmpeg-linked.txt; then
          echo 'FFmpeg dependency escaped the private library directory' >&2
          exit 1
        fi
      done
      runHook postInstallCheck
    '';
    meta = {
      description = "mpv using the private V4L2 Request API FFmpeg";
      homepage = "https://mpv.io";
      license = lib.licenses.gpl2Plus;
      platforms = [ "aarch64-linux" ];
      mainProgram = "mpv-avd";
    };
  };
in { inherit ffmpeg-avd mpv-avd; }
