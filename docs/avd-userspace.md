# Opt-in AVD FFmpeg and mpv

The overlay exposes `pkgs.aurora.ffmpeg-avd` and `pkgs.aurora.mpv-avd`. It does not override `pkgs.ffmpeg` or `pkgs.mpv`, and images do not install the opt-in programs by default. The executables are `ffmpeg-avd`, `ffprobe-avd` and `mpv-avd`. FFmpeg's runtime libraries live in its own store output under `lib/aurora-avd`; presets live under `share/aurora-avd/ffmpeg`, and build headers and pkg-config files are in a separate development output. mpv has a store RUNPATH to that private FFmpeg.

The programs use the same sources as [fedora-aurora#91](https://github.com/aurora-silicon/fedora-aurora/pull/91):

| Component | Pin |
| --- | --- |
| FFmpeg | 8.1, base `9047fa1b084f76b1b4d065af2d743df1b40dfb56` |
| Public V4L2 Request API series | Kwiboo/FFmpeg `b57fbbe50c9b2656fad86a1a7eeabfd2b2a50935` |
| mpv | `41f6a645068483470267271e1d09966ca3b9f413` |
| Request series patch SHA-256 | `36406ad3579e3454eda9c3b9199d6b31dfcf936facf08078a7782dc98d198c6e` |
| mpv DRM import patch SHA-256 | `983f519487674ccc7fe3db2f8ca38034438d867be991339ee51fa2f251f8a8cb` |

The two patches and the request-series provenance are copied byte-for-byte from that reference. FFmpeg enables H.264, HEVC, VP9 and AV1 Request API hwaccels. mpv enables Wayland/EGL, DRM/dmabuf import, ALSA and PulseAudio. Optional features are selected explicitly so installed system mpv dependencies cannot change this build. There is no libva request bridge or browser patch in these packages.

Device access uses systemd's existing `70-uaccess.rules`. Its `media` and `video4linux` tags must remain in every image; `scripts/check-basics.py` checks the finished image, following Nix store links and respecting a local override or mask. No additional group, permission rule or global environment variable is installed.

## Install the built runtime closure

Copy `runtime-closure.nar.gz`, `runtime-closure.sha256`, `ffmpeg-path.txt` and `mpv-path.txt` from the build artifacts into one directory, then run:

```sh
sha256sum -c runtime-closure.sha256
gzip -dc runtime-closure.nar.gz | sudo nix-store --import
nix profile add "$(cat ffmpeg-path.txt)" "$(cat mpv-path.txt)"
ffmpeg-avd -hide_banner -hwaccels
mpv-avd --no-config --hwdec=help
ldd "$(command -v ffmpeg-avd)"
ldd "$(command -v mpv-avd)"
```

This imports the complete aarch64 runtime dependency graph and installs only the two opt-in packages in the user profile.

## Build from source on an aarch64 builder

```sh
nix build -L .#ffmpeg-avd .#mpv-avd \
  .#checks.aarch64-linux.avd-coinstall .#checks.aarch64-linux.media-uaccess
nix profile add .#ffmpeg-avd .#mpv-avd
ffmpeg-avd -hide_banner -hwaccels
mpv-avd --no-config --hwdec=help
ldd "$(command -v ffmpeg-avd)"
ldd "$(command -v mpv-avd)"
```

For a NixOS configuration using this overlay:

```nix
environment.systemPackages = [ pkgs.aurora.ffmpeg-avd pkgs.aurora.mpv-avd ];
```

Both derivations check their help listings. FFmpeg also checks all four hwaccel configuration defines. After fixup, both run `ldd` on their installed executables and reject any FFmpeg dependency outside the private store library directory. The co-install check builds a profile containing stock and candidate programs with collision errors enabled. The media access check reads the actual configured NixOS udev rules. `scripts/build-avd-nix` runs those builds and saves output paths and a compressed complete runtime closure with a SHA-256 receipt.

Rollback: remove the two attributes from `environment.systemPackages` and rebuild, or run `nix profile list` and remove the corresponding `ffmpeg-avd` and `mpv-avd` entries with `nix profile remove`. The global packages are independent.

## Qualification on an AVD machine

Use a known local video for each supported codec. Hardware support still depends on the running kernel, firmware and device generation. A help listing proves the userspace path was compiled, not that a particular stream decoded in hardware.

```sh
ffmpeg-avd -hide_banner -hwaccels
mpv-avd --no-config --hwdec=help
# Silent decode test, with logs showing the chosen decoder:
mpv-avd --no-config --hwdec=v4l2request-copy --vo=null --ao=null \
  --audio=no --msg-level=vd=debug --frames=300 /path/to/video.mp4
# The 4K playback demo, muted:
mpv-avd --no-config --hwdec=v4l2request-copy --audio=no /path/to/4k-video.mp4
```

Require `v4l2request` in FFmpeg, both `v4l2request` and `v4l2request-copy` in mpv, and a log reporting hardware decoding with `v4l2request-copy` during playback. A software fallback is a failed hardware test even when playback works. `--hwdec=v4l2request` is available for separate direct-import qualification; the DRM import patch does not by itself establish working zero-copy on every renderer. Keep hardware qualification logs separate from package build checks.

For a normalized software/hardware frame comparison:

```sh
clip=/path/to/video.mp4
ffmpeg-avd -v error -hwaccel none -i "$clip" -map 0:v:0 -an \
  -pix_fmt yuv420p -f framemd5 software.framemd5
ffmpeg-avd -v verbose -hwaccel v4l2request -i "$clip" -map 0:v:0 -an \
  -pix_fmt yuv420p -f framemd5 request.framemd5 2> request-decode.log
grep -v '^#' software.framemd5 > software.frames
grep -v '^#' request.framemd5 > request.frames
cmp software.frames request.frames
```

Check the decoder log as well as the hashes. For a ten-bit clip use the matching ten-bit software format for both commands. No AVD machine is accessed by the package build checks.
