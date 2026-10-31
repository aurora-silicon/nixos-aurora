# speakerguardd candidate packaging

Upstream review: https://github.com/aurora-silicon/speakerguardd/pull/27

All three draft packaging PRs pin the same candidate, `add7f9610d68b3ff898275d3e7d1cdcd8587c47c`.
Source archive SHA-256: `b016469ad71ae791b2d0b2b0837b7a48708211bee9330c7975588bc939be0c6e`.

| Distribution | Package version | Native integration |
| --- | --- | --- |
| Fedora | 0.1.13~rc2-1 | RPM, Python retention helper, optional xlim subpackage |
| Arch Linux ARM | 0.1.13rc2-1 | PKGBUILD, Python retention helper, optional LADSPA plugin |
| NixOS | 0.1.13-rc.2 | Hash-pinned source and Cargo lock, patched helper interpreter, optional LADSPA plugin |

Upstream DT/ALSA profile selection and the refusal of unqualified profiles
remain effective. V/I profiles are packaged but are not silently qualified or
automatically enabled. The existing J700 feedback-owner condition stays in
place. No device-specific service override or state-persistence stopgap is
introduced. The optional xlim plugin is installed without enabling a graph.

The Rust acceptance suite, retention tests and xlim tests remain required in
native package checks. Upstream's strict listening assertions remain release
gates; do not bypass checks to publish this candidate. These PRs prepare
source parity, not a claim of successful native packages or fleet rollout.
Production async-ring clean-stop certification still needs the separate
outside-contributor PR #26; it is excluded from this integration.

Before deployment, upstream acceptance and native package builds must pass.
Keep the currently governing protection and existing fallback active during any
separately authorized rollout. This change performs no installation, service
change, audio test, or hardware access.

The RC2 source reconciles main #17/#20/#29 with RC #27/#28. It retains
state generation 3, the external `/run/speakerguardd.unlocked` marker,
fail-closed state writes (C1), and latched V/I starts (C2). Only the J700
single-model path can use the reviewed evidence start. The two strict
ordinary-listening assertions still fail under the linear transfer contract;
they remain required checks. A tighter justified transfer bound and an
independent safety review of this candidate are required before release.
The native-float grant work in upstream #30 remains a separate stacked PR.

Stage upgrades for activation across an orderly reboot. Fedora uses the
non-restarting postun macro; the old installed package's scriptlets also
need checking before a transaction. Arch's recipe has no restart hook.
For NixOS prepare the next boot generation with `nixos-rebuild boot`, keeping
the governing generation until reboot. Preserve the independent fallback
and the current model/record/marker evidence. A generic package update must
not remove a marker or force a runtime state to appear cold.

The previous pin `526790d` failed three tests in native distro CI (Fedora
41194590811, Arch 41194590761, Nix 41194590907), including the retained
unknown-start safety oracle. This pin restores the legacy model's own
conservative drain peak and preserves overflow rejection. The original
oracle and its 1e-8 comparison remain unchanged. All 116 source-file contents in the public archive match Git byte for byte. The listening fixes
remain a separate follow-up; native package acceptance must still
pass before release. Keep these source-only drafts unmerged and do not
install rc.2 on M1 Pro, M2 or J616s. No deployment is part of this change.

The latest source also retains a nonfinite interval peak when both drain
endpoints are finite. A separate fast-coil regression covers that case;
the original hot-node oracle and its tolerance remain unchanged. Final
validation of this exact pin is required before release.
