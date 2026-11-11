# AVD VA-API driver

Aurora NixOS packages the public `omacom/libva-v4l2_request` `avd-fixes`
branch at commit `4f60c51f7841dd74bb61c94a4ad31e630bbdab01` as
`libva-v4l2-request-avd`. The package is part of the graphics driver closure,
which exposes these names to libva:

```text
/run/opengl-driver/lib/dri/v4l2_request_drv_video.so
/run/opengl-driver/lib/dri/asahi_drv_video.so -> v4l2_request_drv_video.so
/run/opengl-driver/lib/dri/aurora_drv_video.so -> v4l2_request_drv_video.so
```

The relative aliases cover the older and current render-node driver names, so
normal discovery selects the driver. The module sets no global
`LIBVA_DRIVER_NAME`, browser preference, permission rule, or sandbox exception.
It supersedes the older opt-in package supplied by the Apple-silicon module
without enabling that module's global driver override.

Validate with `env -u LIBVA_DRIVER_NAME vainfo --display drm`. For licensed
H.264, HEVC, VP9 and AV1 clips, compare `ffmpeg -hwaccel vaapi` frame MD5 output
with software and run mpv muted with both `--hwdec=vaapi` and
`--hwdec=vaapi-copy`. Run Firefox in the normal RDD sandbox and capture its
`about:support` Media/Graphics sections plus
`MOZ_LOG=PlatformDecoderModule:5,FFmpegVideo:5`. Software fallback and sandbox
denial are failures, not hardware passes.

## Firefox

Firefox's RDD sandbox does not admit the media controller node and the four
media/request ioctls that libva-v4l2-request needs, so stock Firefox decodes in
software. The overlay adds `patches/firefox-rdd-v4l2-request.patch` (Mozilla
bug 2080696, the same patch as fedora-aurora and alarm-aurora) to
`firefox-unwrapped`; nixpkgs' `firefox`, and so `programs.firefox`, wraps it.
CI builds it as the `firefox` output and the Aurora cache serves it, so every
nixpkgs update that moves Firefox rebuilds it.
