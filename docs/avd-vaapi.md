# AVD VA-API driver

Aurora NixOS packages the public `omacom/libva-v4l2_request` `avd-fixes`
branch at commit `4f60c51f7841dd74bb61c94a4ad31e630bbdab01` as
`libva-v4l2-request-avd`. The package is part of the graphics driver closure,
which exposes these names to libva:

```text
/run/opengl-driver/lib/dri/v4l2_request_drv_video.so
/run/opengl-driver/lib/dri/asahi_drv_video.so -> v4l2_request_drv_video.so
```

The relative alias makes normal render-node discovery select the driver. The
module sets no global `LIBVA_DRIVER_NAME`, browser preference, permission rule,
or sandbox exception. It supersedes the older opt-in package supplied by the
Apple-silicon module without enabling that module's global driver override.

Validate with `env -u LIBVA_DRIVER_NAME vainfo --display drm`. For licensed
H.264, HEVC, VP9 and AV1 clips, compare `ffmpeg -hwaccel vaapi` frame MD5 output
with software and run mpv muted with both `--hwdec=vaapi` and
`--hwdec=vaapi-copy`. Run Firefox in the normal RDD sandbox and capture its
`about:support` Media/Graphics sections plus
`MOZ_LOG=PlatformDecoderModule:5,FFmpegVideo:5`. Software fallback and sandbox
denial are failures, not hardware passes.
