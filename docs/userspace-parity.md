# Userspace package parity, 2026-10-31

Update 2026-11-08: the v2 rollout is held. This candidate carries Fedora's
legacy speaker-protection patch on the current kernel/DTB source, restores
the Asahi speaker graphs in audio release aurora12, and retires v2's package
and services. Native Nix evaluation, builds and device qualification remain
required before publication. The parity entries below are historical.

The Fedora main snapshot is the packaging baseline. Package release labels
track the same merged content using each distribution's existing version scheme.

| Package | Fedora | Arch Linux ARM | NixOS | Source identity |
| --- | --- | --- | --- | --- |
| aurora-sep | 1-14 | 1-14 | 1.14 | Vendored integration from linux `7cc30f35ecea3e90ceedd44babbde128c1d487a6`, with the already merged Touch ID setup adaptations |
| aurora-audio / asahi-audio | 4.1-7 | 4.1.aurora2-7 | 4.1-aurora7 | asahi-audio `d957fabbacbe7dd67b39f052b2ff21edea7ee038` |
| speakerguardd-v2 (the only speaker stack since 2026-11-28; see below) | 1.0.0~alpha.2-0.64.20261128gite0672aca6aa3 | 1.0.0alpha.2-14 | 1.0.0-alpha.2 | speakerguardd main `e0672aca6aa310bfecfd5c581043e016b085239a` |

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

## 2026-11-28: speakerguardd v2 is the only speaker stack

speakersafetyd, speakersafetyd-aurora-profiles and speakerguardd 0.1 are no
longer packaged in any of the three distributions, and aurora-audio installs
no Asahi speaker graph, speaker FIR or raw speaker volume lock (its
microphone graphs, jack and card rules and the speaker period-interrupt rule
stay). An existing install loses them on the upgrade:

| | Fedora | Arch Linux ARM | NixOS |
| --- | --- | --- | --- |
| aurora-audio | 4.1-18: Obsoletes speakersafetyd < 2.0.1-2, speakersafetyd-aurora-profiles < 1-2 (the builds we shipped), speakerguardd < 0.2, asahi-audio < 4.1-18; requires speakerguardd-v2 and aurora-speaker-upgrade | 4.1.aurora2-19: replaces speakersafetyd<2.0.1-2 and speakersafetyd-aurora-profiles<1-3 (the builds we shipped), replaces and conflicts with speakerguardd<0.2 | asahi-audio 4.1-aurora18; speakerguardd 0.1 is no longer packaged, speakersafetyd is an empty package (nixos-apple-silicon still names it) and `speakersafetyd.service` is masked; v2 and the upgrade tool are always on |
