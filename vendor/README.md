# Neo Stage 2 payload

`boot-j700.bin` is the 9,277,502-byte boot payload from the published Omarchy Neo image audited in `work/omarchy-neo-boot-20261018/kernel-dtb-audit.json` (image build 39131261984). SHA-256: `0481c2d5d75c93300be6f7c2187746cd06b769f48c6538b134044aabe930b8d2`.

That exact payload booted Neo through GRUB into NixOS KDE after the larger generic payload failed to chainload. The image bundle carries it beside the generic payload; the installer chooses the dedicated file only for Neo. Stage 1 remains the enrolled file already on the Mac during Reset.
