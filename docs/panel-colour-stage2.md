# Panel colour and the Stage 2 device tree

Linux [#1021](https://github.com/aurora-silicon/linux/pull/1021) adds
`apple,color-gamut = "display-p3"` to the J614s, J616s and J616c panel nodes.
The DCP driver uses the standard Display P3 target when firmware supplies no
complete chromaticities. Both the new driver and the new device tree are
needed: installing only the kernel while retaining an older embedded DTB
leaves the panel without its target colour space.

`overlay.nix` builds the pinned kernel and its DTBs. The Apple Silicon module combines them with aura and U-Boot as `system.build.m1n1`; `modules/installed.nix` validates that image and refreshes the ESP through `aurora-install-stage2`, keeping the previous image.

`sources.json` pins the kernel through the merge of #1021,
`e5ed737692b0ad07e212d210b568914b4fc01aca`. The kernel build checks the
`apple,color-gamut` property in each of the three generated DTBs before
packaging. The aura package supplies a bare bootloader binary; it does not
own these panel properties. Changing the aura version alone cannot refresh
an embedded DTB.

After updating the kernel and refreshing Stage 2, verify the live tree's
`/dcp@402e00000/panel/apple,color-gamut`, then decode the internal panel EDID
with `edid-decode`. A J616s should report Red 0.6796/0.3203, Green
0.2646/0.6904, Blue 0.1503/0.0595 and Gamma 2.20. Check the normal boot,
not only a trial image: no GNOME `bogus Color Characteristics` message,
no priority-3 journal entries and no SELinux AVCs. Retain the previous Stage 2
and its checksum until the refreshed payload is qualified. Stage 1 enrollment
is separate from this refresh.

A source pin or DTB build check establishes payload contents, not hardware
qualification or publication. Qualify the complete kernel/Stage 2 combination
before promoting the distribution artifacts.
