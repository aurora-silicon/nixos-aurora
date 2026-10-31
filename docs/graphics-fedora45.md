# Graphics source parity: Fedora 45

| Distribution | Native Mesa source pin | FEX x86_64 + i686 | Package identity |
| --- | --- | --- | --- |
| Fedora | `9fe179df8bf1cec359d9e452fc9dfa8680285698` | same pin and archive | `1:26.3.0-14.fc45.aurora` |
| ALARM | `9fe179df8bf1cec359d9e452fc9dfa8680285698` | same pin and archive | `1:26.3.0_devel.202610310601.9fe179df8bf-1` |
| NixOS | `9fe179df8bf1cec359d9e452fc9dfa8680285698` | same `sources.json` record through the overlay | `26.3.0`, fixed-output archive hash |

This table records source parity, not output parity: Fedora builds the six
native outputs plus FEX; ALARM splits Rusticl/lavapipe from the same native build;
the NixOS native recipe currently enables neither Rusticl nor lavapipe.

Archive SHA256: `c174eed7713256efd3a4289f34f5c529ebefffc227989e721bcc335ff90dd2a0`.
The shared Mesa source includes [mesa#122](https://github.com/aurora-silicon/mesa/pull/122).

See the [Fedora build and transaction procedure](https://github.com/aurora-silicon/fedora-aurora/blob/main/docs/graphics-fedora45.md)
for the Fedora 45 candidate workflow and public fc44 rollback baselines.
This change aligns source pins; it does not claim ALARM/NixOS package builds
or generation-switch/rollback qualification. Flatpak recipe metadata moves
only to preserve the existing tracker lockstep contract; its implementation
and runtime validation remain separate work.
