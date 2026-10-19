# SEP state ownership

The driver uses this machine's iBoot System Container and its own private
Linux identity. It accepts shared xART writes only after validating APFS
extent ownership, records and write ordering. Unsupported layouts fail closed.
The loader never replaces an existing identity. Raw partition restoration does
not reverse secure-enclave anti-replay state.

Keep a verified read-only backup before first hardware qualification. Never copy
identity or calibration files between Macs. Read-only diagnostics can select
`xart_writes=0 provision_keybag=0`; that does not provision trusted keys.

The driver and its ownership checks are pinned in `sources.json`. The upstream
`tools/aurora-sep/XART-SAFETY.md` records the qualified layouts and limitations.
