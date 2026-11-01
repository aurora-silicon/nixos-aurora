# AVD firmware changelog

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
