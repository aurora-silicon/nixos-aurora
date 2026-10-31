# Demo package parity

| Component | Fedora | Arch Linux ARM | NixOS |
| --- | --- | --- | --- |
| aurora-try | Pending public source | Pending public source | Pending public source |
| camera-denoise | Existing package, preset disabled | Existing package, global enable hook removed | Existing package, module defaults false |
| Camera effects backend | Pending public source pin | Pending public source pin | Pending public source pin |
| capture-ns `f843fd3` | `aurora-capture-ns` | `aurora-capture-ns` | `capture-ns` flake output |
| RNNoise `6cbfd53` | `aurora-rnnoise` | `aurora-rnnoise` | `rnnoise` flake output |
| libDF `d375b2d` | `aurora-libdf` | `aurora-libdf` | `libdf` flake output |
| Whisper `e65f3c4`, Vulkan + Linux ANE adapter | `whisper-cpp-aurora` | `whisper-cpp-aurora` | `whisper-cpp-aurora` flake output |
| Compiler `3837b4c`, linked H13 and MobileNet tools | `mil-hwx-compiler` | `mil-hwx-compiler` | `mil-hwx-compiler` flake output |
| First-run SHA-256 model fetcher | `aurora-models` | `aurora-models` | `aurora-models` flake output |
| Defaults | Opt-in, no device selection | Opt-in, no device selection | Opt-in, no device selection |

Fedora and ALARM build the capture plugin and its two model libraries together,
then ship separate packages at the capture stack release version. The exact
upstream library versions/revisions are in sources.json. Nix builds separate
derivations from those same archives. Both model libraries have private or
store paths, so the launcher cannot accidentally load a different system ABI.

The runtime model manifest and helper code are identical across all three
repositories. RNNoise's BSD-licensed built-in arrays are the only embedded
weights in these binary packages. libDF's capi-to-default-model feature edge
is removed; DF3 and Whisper weights are downloaded only when requested.
The source/SRPM for libDF contains its original MIT/Apache-licensed model
archive, which is needed by the synthetic C API check. It is not a runtime
model package. See LICENSE-AUDIT.md for the repository-grant qualification.

Capture currently uses libane's CPU fallback API only. Whisper auto prefers
an explicitly supplied compiled open ANE bundle, then hardware Vulkan, then
CPU. The native adapter's failure policy retries CPU, not Vulkan, within an
utterance. Nothing here qualifies an uncompiled model on ANE.

The arm64 package VM has 4 KiB pages and no target GPU/ANE. Native build logs
qualify package construction and synthetic tests only. The lead must verify
16 KiB kernels, Borealis and any native ANE bundle on M1 Pro/M2. See TRY.md and
LEAD-RUN.md. No audio playback or microphone recording is part of build checks.

Recommend `TAG+="uaccess"` in the runtime's ANE udev rules rather than automatic
`accel` group membership. These consumer packages install no ANE permissions
policy. A headless SSH session does not acquire a logind seat ACL by itself.

Compiler: all three recipes pin merged `3837b4cc2f432754970dbff0f61a3397fede7478`, with linked/linked-l2 and the H13 MobileNet runner. Native compiler package validation remains pending. Aurora-try main now includes camera, mic-denoise, OCR, classify and captions per the lead; the repository still reports private, so these packages await a public source release.
