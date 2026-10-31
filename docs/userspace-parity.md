# Userspace package parity, 2026-10-31

The Fedora main snapshot is the packaging baseline. Package release labels
track the same merged content using each distribution's existing version scheme.

| Package | Fedora | Arch Linux ARM | NixOS | Source identity |
| --- | --- | --- | --- | --- |
| aurora-sep | 1-14 | 1-14 | 1.14 | Vendored integration from linux `7cc30f35ecea3e90ceedd44babbde128c1d487a6`, with the already merged Touch ID setup adaptations |
| aurora-audio / asahi-audio | 4.1-7 | 4.1.aurora2-7 | 4.1-aurora7 | asahi-audio `d957fabbacbe7dd67b39f052b2ff21edea7ee038` |
| speakerguardd | 0.1.12-1 | 0.1.12-1 | 0.1.12 | speakerguardd main `34aeed9085ad0f66cb8f266f997e11dd781470a6` |

Arch retains `4.1.aurora2` so this remains an upgrade from `4.1.aurora2-4`.
Nix keeps the upstream audio version in sources.json and adds the Fedora
packaging release to the derivation version. SEP's Nix version advances from
1.9 to 1.14, following its existing version/release encoding.

The SEP loader, readiness helper, sensor-presence helper, calibration reader,
Touch ID setup tool and setup-needed helper are byte-identical in all three
repositories. Distribution-specific service paths, firmware publication and
SELinux integration remain in their existing recipes/modules. SEP is vendored
from linux tools/aurora-sep; aurora-sep-userspace main
`61a76b575b8cf1726575e7b748ef375298e78f6d` is the separate libfprint source,
not the origin of this integration package.

The audio pin and merged asahi-audio main
`24124037030d7df339f3cc99113b6773055455f6` have the same Git tree:
`9177eb7180e412802d0ed605754ee603f6a0ed4e`. Fedora and Arch require WirePlumber
0.5.16 or later. Nix pins nixpkgs `e7439b6b14ad3cc35d05608ebca9bce01a25f5f8`,
which supplies WirePlumber 0.5.18.

Fedora already has all three target versions, so its parity change records the
audit without rebuilding an artificial package release. Arch and Nix only change
SEP/audio version labels. speakerguardd source, behavior, profiles, service
settings and protection interlocks are unchanged. No unmerged speaker changes
are included. The merged libfprint aurora6 updates are outside this change.
