# AVD firmware changelog

## 2026-11-21: ea8ae7c8

Update the pinned MIT-licensed firmware to
`ea8ae7c8b19057865b99f16522e122566dabdaf4` (avd-fw#8), which maps the v4
(T8122) SRAM at `+0x90000`. Only `avd-fw-v4-t0.bin` changes: it is now padded
to 0x10000 bytes instead of 0x12000, SHA-256
`92d30e532e9c9d0f3dcd0c8d689aec474696106b28338d5b5b4e127caec88c6f`. The
other seven images are byte-identical to 6062e851.

On a J615 (M3 Air), the open-queue transport needs the matching device tree
(linux#2586); with the current device tree the driver falls back to the
legacy transport, and decoding stays bit-exact either way. Keep upstream Meson
defaults and the clang 22 toolchain requirements. Source archive SHA-256:
`ebf4fae6872c4e6dc5747fb98a613b790cc9e0c9aa4c9bf3e0f96e3afcc369da`.

## 2026-11-01: 6062e851

Update the pinned MIT-licensed firmware to
`6062e8516c0a751bc8e50f5d604a17395923189f` for per-image codec VP pools and
multi-VP decoding. Ship all eight images, including the new `avd-fw-v3-t2.bin`.

Keep upstream Meson defaults and the clang 22 toolchain requirements. The
package check prints and enforces all eight expected SHA-256 hashes, image
sizes, ARM ELF headers and reset vectors. Host build flags stay cleared or
disabled. Source archive SHA-256:
`49a631c8ba0c87bac187376bc642acaad1f62791dde6ed285fbc2bad21d60cf0`.

## 2026-11-01: 66c3911b

Update the pinned MIT-licensed firmware to
`66c3911bbaebdca90a179aa74c7addde9b2963ce` for queue ABI 2 with the SRAM
ring and VP DONE events. Install all seven images, including `avd-fw-v5-t2.bin`
for T6040, alongside v5-t1 for fallback.

Use upstream Meson defaults (`optimization=2`, `debug=false`) with host build
flags cleared or disabled. The package check prints and verifies all seven
clang 22 image SHA-256 hashes as well as sizes, ARM ELF headers and reset
vectors. A different toolchain must pass the same checks; mismatches fail the
build and require investigation rather than replacing the expected hashes.

Provide a wrapped native clang for the upstream queue test while the bare-metal
firmware continues to use unwrapped clang. Run the queue test during checks.
