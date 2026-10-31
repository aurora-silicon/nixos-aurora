# Lead run

Use [TRY.md](TRY.md) for exact start/off commands on M1 Pro and M2.
Install only packages from the same checked build. Nothing enables a service
or changes a default device. Do not change the playback graph, UCM or speaker
protection for these demos.

1. Verify package installation leaves `aurora-camera-denoise.service` disabled
   and creates no capture service or persistent PipeWire fragment.
2. Run `whisper.cpp-aurora --engine auto -f "$HOME/aurora-demo.wav"` on a chosen
   existing file. Expect an engine line, one verified model download and text.
   Repeat with `--engine cpu`. Off is Ctrl-C or normal process completion.
3. Only in the morning, choose the explicit internal microphone node from
   `pw-dump`, set `AURORA_MIC_NODE`, then run the capture command in TRY.md.
   Select its virtual source in the application manually. Off is Ctrl-C;
   confirm that only its virtual source disappears and defaults stay unchanged.
4. Record host model, distro, kernel page size, chosen engine and the full
   command with any measurements. The package VM has 4 KiB pages; it does not
   qualify 16 KiB Mac kernels or Borealis/ANE inference.

There is no worker device receipt. Native package checks use the shared arm64
VM/container and synthetic buffers, with no recording or playback. Preserve
failed ANE worker receipts locally and follow the runtime's recovery policy.
Do not substitute Apple-compiled programs for missing open encoder bundles.

The effects backend and aurora-try pin are pending public source availability.
Do not install a private checkout to fill that gap in this packaging review.
