# Aurora splash geometry

The logo stays in the pixels where aura drew it. Coordinates use device
pixels (`DeviceScale=1`); the existing 128/256 px logo choice is unchanged.

## Platform data

`aurora-plymouth` runs before `plymouthd` on each boot and writes
`/run/plymouth/aurora.script`. It prepends three numeric values to the
installed script, without modifying `/usr`, `/etc`, or the Nix store.
The theme descriptor selects that generated script. Machine values never
come from the image builder, and no machine table or notch offset is shipped.

The helper reads the live DT at `/sys/firmware/devicetree/base`:

- `/chosen/framebuffer*/{width,height,stride,reg}` describes the boot scanout.
- `/reserved-memory/framebuffer*/reg` describes the original framebuffer
  reservation, with the `framebuffer` compatible string. aura retains its base
  while advancing the chosen framebuffer base past the hidden rows.
- `/aliases/dcp` identifies the DCP node with `apple,notch-height` when present.

The hidden row count is `(chosen_base - reserved_base) / stride`. The helper
requires one enabled boot framebuffer and one containing reservation, whole
rows, and sufficient reserved space. This also works when the DCP property is
missing or stale. For a loader that keeps the whole panel, the base difference
is zero and the DCP property supplies the notch height. The panel height is
the chosen height plus the hidden rows. DT cells are decoded as big endian.

The kernel's `show_notch` parameter describes the driver's policy, rather
than the physical origin of the inherited framebuffer. DRM connector modes
can appear after the splash starts. Neither supplies the missing origin at
early startup, so this theme uses the DT and rechecks display dimensions
whenever Plymouth changes the mode.

If the view width matches the panel and the view height is exactly
`panel_height - notch_height`, the logo y is
`floor((panel_height - logo_size) / 2) - notch_height`.
Otherwise it is `floor((view_height - logo_size) / 2)`. This subtracts the
whole hidden origin from aura's panel coordinate. Relative to centering in
the cropped view, the movement is half the notch height for even heights.
The full-height mode stays centered. Flooring before subtracting also handles
odd notch heights exactly.

When another selected theme omits Aurora's source from the initramfs, the
helper exits successfully without creating a script or changing its startup.
Missing, truncated, translated or ambiguous DT data produces zero geometry
and the ordinary centre rule. The script plugin exposes dimensions without
connector identity, so an external display with identical pixel dimensions
cannot be distinguished from the internal panel.

## Initramfs integration

- Fedora: the `96aurora-plymouth` dracut module installs the helper, its tools,
  and the `plymouth-start.service` pre-start command. A `pre-trigger` hook also
  supports dracut without systemd. Rebuild the initramfs after installing.
- ALARM: the package's mkinitcpio configuration inserts `aurora-plymouth`
  immediately before an existing `plymouth` hook, keeping every other hook in
  order. It installs the helper and service pre-start command, plus a runtime
  hook for initramfs builds without systemd. Rebuild with `mkinitcpio -P`.
- NixOS: the module extends the systemd initrd's `plymouth-start` pre-start
  script, after the stock runtime links are created. It also prepares the
  script for a daemon started in the real root. The helper and coreutils enter
  the initrd through the service closure; the geometry is read at boot.

The helper must also run before a manual `plymouthd` start outside these
services. Removing the package and rebuilding the initramfs removes its
hooks. To roll back a deployed test, restore the previously saved package,
Plymouth configuration and initramfs together. This change does not alter
bootloader configuration or framebuffer memory.

## Offline checks

`python3 test_geometry.py .` tests the helper against synthetic DT trees.
`render/render.sh` captures Plymouth's real script plugin under Xvfb;
`render/measure.py` locates the logo independently, compares every logo pixel
with aura's PNG and fails unless its panel rectangle matches aura's.
The fixtures include both a cropped loader framebuffer and a full-panel
loader framebuffer, plus both Plymouth modes from a cropped loader.

| Panel | Full size | Hidden rows | Cropped-view logo | Full-view logo | Physical logo |
|---|---|---|---|---|---|
| J616s | 3456x2234 | 74 | (1600,915), 256 px | (1600,989), 256 px | (1600,989), 256 px |
| M2 J413 | 2560x1664 | 64 | (1152,640), 256 px | (1152,704), 256 px | (1152,704), 256 px |
| Neo J700 | 2408x1506 | 0 | (1076,625), 256 px | (1076,625), 256 px | (1076,625), 256 px |

The render harness also checks a missing DCP property and an odd notch height.
It hides, re-shows and quits each splash. These are offline checks, not a
claim of a physical boot test.

A Fedora render container can run the same source from any of the three
repositories. With the theme directory as the working directory:

```sh
docker build -f render/Containerfile -t aurora-plymouth-render render
mkdir -p render/out
docker run --rm -v "$PWD:/w/theme:ro" -v "$PWD/render:/w/render:ro" \
  -v "$PWD/render/out:/w/out" aurora-plymouth-render \
  bash /w/render/render.sh /w/out
```

## Public implementation sources

- [aura framebuffer handoff](https://github.com/aurora-silicon/aura/blob/e7e69a4e6c9ae8c5cc7f071f1b0e0def880cabe0/src/kboot.c):
  `get_notchless_fb`, `dt_set_fb` and `dt_vram_reserved_region` describe the
  cropped base, dimensions, DCP property and original reservation.
- [aura logo placement](https://github.com/aurora-silicon/aura/blob/e7e69a4e6c9ae8c5cc7f071f1b0e0def880cabe0/src/fb.c):
  `fb_blit_logo` centres the unscaled logo in the full boot framebuffer.
- [Public kernel DCP code](https://github.com/aurora-silicon/linux/blob/5d7c3e74019d0a04a22e0c6e5cec5a297e245fd6/drivers/gpu/drm/apple/dcp.c)
  reads `apple,notch-height` at probe unless `show_notch` is selected.
  [Mode parsing](https://github.com/aurora-silicon/linux/blob/5d7c3e74019d0a04a22e0c6e5cec5a297e245fd6/drivers/gpu/drm/apple/parser.c)
  subtracts that height from the visible mode.
- [aurora-diag display collection](https://github.com/aurora-silicon/aurora-diag/blob/43c9762c956fd6f33e6936a0cbd68cfc4bcc7920/aurora_diag/sections.py)
  reads the same DCP property, and reports its absence separately from a
  no-notch panel.

The helper and fixtures are original MIT-licensed code. The referenced aura
and kernel implementations are publicly licensed sources; no firmware or
private device records are included.
