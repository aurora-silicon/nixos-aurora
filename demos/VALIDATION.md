# Package validation (in progress)

These are draft packages. Aurora-try and camera effects still need publicly
fetchable source archives. The existing camera packaging is extended and opt-in.
The compiler source is merged main 3837b4cc2f432754970dbff0f61a3397fede7478.

| Component | Fedora | Arch Linux ARM | NixOS |
| --- | --- | --- | --- |
| Model helper | Release 1 built in native ARM VM; release 2 built/linted in ARM64 container on x86 buildbox | Release 2 built natively and installed | Evaluation/build pending |
| Vulkan Whisper | C++/unit checks completed in ARM64 buildbox container; RPM 6 license metadata failed and is fixed in source; rebuild pending | Native package built; 5 CTest units and 7 worker tests passed | Evaluation/build pending |
| Compiler + graph runner/bridge | Bootstrap reached GNUstep install; missing which dependency fixed; rebuild pending | Installed file test/compiler phase queued | Compiler derivation evaluated; native build pending |
| Capture/RNNoise/libDF | Two libDF attempts interrupted; source/logs and partial O2 cache preserved | Deferred native phase | Deferred native phase |

Native ARM VM: Fedora 44 aarch64, 4 KiB pages, hosted on the macOS Mac mini M2
build host. ALARM runs in its container. The buildbox fallback is an ARM64
container under QEMU on an x86_64 host; it does not qualify native ARM execution.
No GPU/ANE, 16 KiB kernel, microphone or speaker test is claimed here.

The shared helper/engine suite passes 10 tests per repository on the macOS
Mac mini M2 host. Fedora's focused recipe/helper suite passes 19 there.
ALARM also passed the 10 helper tests in the native ARM VM.
Real RNNoise, DF3 and Whisper downloads verified on the macOS host and with
the release-1 helper RPM in the Fedora ARM VM. The helper runtime code is
unchanged in release 2; its serializer install metadata and docs were corrected.

The native ALARM Whisper package is
`whisper-cpp-aurora-1.9.5-1-aarch64.pkg.tar.xz`, SHA-256
`1ece2b74d45dfcac5bf99c10f471185a17139d6226647106c2831604e6713d00`.
The macOS build host inspected both runtime ELF binaries: machine aarch64,
PT_LOAD alignment 65536, with offsets congruent for 16 KiB pages. This is a
structural check, not target-kernel execution. The installed file smoke and
namcap remain pending; the initial test driver incorrectly assumed .zst output.

See build-logs/alarm-whisper.log for the native build/check/package tail and
build-logs/fedora-models-rpmlint.log for the corrected helper lint (0 errors,
0 warnings, ARM64 container on x86 buildbox). Full raw logs and failed attempts
are preserved by the task operator; these excerpts contain no private lab input.

The Fedora RPM 6 file-list failure mixed relative and absolute %license paths on one line; the recipes now separate them. Compiler recipes declare which/gzip for GNUstep make install. These corrections still require full package rebuilds. Nix evaluated the scoped model-helper source and compiler derivation with import-from-derivation disabled; the full flake check has not completed.
