# speakerguardd candidate packaging

Upstream review: https://github.com/aurora-silicon/speakerguardd/pull/27

All three draft packaging PRs pin the same candidate, `221c8bfa2ac4aa43a1f9075420a95c1d12bce4b0`.
Source archive SHA-256: `17b77fa6c0117eb3a546b798b375ae131b461f78e4479f40615bf2d01b7b909d`.

| Distribution | Package version | Native integration |
| --- | --- | --- |
| Fedora | 0.1.13~rc1-1 | RPM, Python retention helper, optional xlim subpackage |
| Arch Linux ARM | 0.1.13rc1-1 | PKGBUILD, Python retention helper, optional LADSPA plugin |
| NixOS | 0.1.13-rc.1 | Hash-pinned source and Cargo lock, patched helper interpreter, optional LADSPA plugin |

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
