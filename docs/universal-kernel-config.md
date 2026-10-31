# Universal hardware configuration

Every supported Mac uses the same source-pinned Apple hardware fragment. A
retained distribution base supplies desktop/security/filesystem/peripheral
policy; a device name never selects a different kernel configuration.

| Configuration input | Before | After |
| --- | --- | --- |
| Shared hardware | Source `arch/arm64/configs/asahi.config` plus local copies | Source fragment is the sole hardware overlay |
| Per-device fragments | None | None |
| Local common hardware copy | 80 requests in `common.config` | Removed; generic peripheral policy retained in the distro base |
| Distribution policy | Full distro base + `nixos.config` | Retained |
| Resolution | `olddefconfig` | `olddefconfig`, then strict ordered fragment validation |

The retired Fedora Neo fragment requested `PCIE_APPLE_PIODMA_DIAG=y`,
`MT7932_FULLMAC=m`, `BT_MTK7932_PCIE=m`, `SPI_APPLE_QSPI=m`,
`RTC_DRV_APPLE_PMU=m`, and `DRM_ACCEL_ANE=m`. All six are already requested by
the pinned shared fragment. The distro recipes must not repeat them in an
overlay: when a source update renames a prerequisite, its hardware fragment
must change with it.

The current pin, `5d7c3e74019d0a04a22e0c6e5cec5a297e245fd6`, is on
`integration/aurora`. Its fragment still requests the old PCIe symbol and
has no `VIDEO_APPLE_AVE`. The `aurora-wip` fragment at
`8348f8244b208b5185b0764ebb21183a678e9e86` requests
`PCIE_APPLE_T8140_BOOTSTRAP=y` and `VIDEO_APPLE_AVE=m`.
Kernel PRs #649, #650, #656 and #657 merged into `aurora-wip`; changing a
distro config cannot add their implementations to an integration pin.

| Feature | Required source/config contract |
| --- | --- |
| Radio bootstrap (#649) | Shared fragment selects `PCIE_APPLE_T8140_BOOTSTRAP=y`, retaining `MT7932_FULLMAC=m` and `BT_MTK7932_PCIE=m` |
| AVE | Shared fragment selects `VIDEO_APPLE_AVE=m` |
| ANE | Shared fragment selects `DRM_ACCEL_ANE=m` |
| ADMAC/I2C runtime PM (#657) | `PM=y`, `APPLE_ADMAC=m`, `I2C_APPLE=m`; runtime behavior is a source change |
| USB4 PCIe tunnels (#650) | `USB4=m`, `USB4_APPLE_SOC=m`, `RESET_APPLE_CIO=y`, `PCIE_APPLE=y`; DT-driven behavior is a source change |
| DRAM reporting (#656) | `APPLE_PMP_REPORT=y`; reporting is a source change |

KUnit options added by these source changes are test options, not hardware
admission switches. Configuration resolution and source checks do not prove
device boot, runtime PM, encoding, radio or tunnel operation.

Nix now merges `asahi.config` before `nixos.config`. Previously its configure
phase only validated the fragment against a retained Arch config.
