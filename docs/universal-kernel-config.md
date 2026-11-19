# One kernel configuration

Every Aurora kernel, on every supported Mac and in every distribution, is
configured by the kernel source itself:

    make ARCH=arm64 LLVM=1 aurora_defconfig

`aurora_defconfig` merges `arch/arm64/configs/asahi.config` (every Apple SoC
and board driver the tree supports, M1 through M5 and A18) over
`arch/arm64/configs/aurora-base.config` (the generic distribution base:
filesystems, networking, security, peripherals) and resolves the result with
`olddefconfig`. No device, chip or distribution selects a different set of
options, and no package carries a base config or an overlay of its own.

| Input | Fedora (kernel-aurora) | Arch Linux ARM (linux-aurora) | NixOS (pkgs/kernel.nix) | Fleet build |
| --- | --- | --- | --- | --- |
| Configuration | `aurora_defconfig` | `aurora_defconfig` | `aurora_defconfig` | `aurora_defconfig` |
| Release name | `make LOCALVERSION=-<release>.aarch64` | `CONFIG_LOCALVERSION="-ARCH"` + `localversion.10-pkgrel` | empty (modDirVersion must equal the version) | `make LOCALVERSION=-aurora-<cut>` |
| Validation | both fragments survive resolution | both fragments + desktop requirements | both fragments + `kernel/nixos.config` + `check-required.py`; the vendored `kernel/config` snapshot must equal the resolved config | both fragments |

The release name is the only per-distribution difference, and it is not a
kernel option: Arch's boot tools find device trees under
`/lib/modules/*-ARCH`, Fedora's kernel-install names the RPM release, and
NixOS requires an empty suffix. `kernel/nixos.config` is a list of what NixOS
needs, checked against the resolved configuration and never merged.

NixOS evaluates kernel options before building, so it vendors the resolved
`aurora_defconfig` in `kernel/config` together with the kernel commit and
SHA256 in `kernel/provenance.json`. The build regenerates the configuration
from the pinned source and fails if it differs from the snapshot; refresh the
snapshot whenever the kernel pin changes. Options an owner sets through
`boot.kernelPatches` are the only thing merged on top.

To change an option, change the kernel source: Apple hardware in
`asahi.config`, everything else in `aurora-base.config`.
