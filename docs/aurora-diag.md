# aurora-diag

`aurora-diag` is the bring-up and regression tool for Aurora on Apple
silicon. It lists sensors, clocks, hardware blocks, services and the GPU
APIs, says what works and what does not, and has `check`, `snapshot`,
`diff` and `report` commands for comparing kernels. `aurora-panic-log`
prints the last panic iBoot kept for the next OS and any kdump crash
dumps. Source: https://github.com/aurora-silicon/aurora-diag (MIT).

It is off by default. Turn it on with:

```nix
aurora.diag.enable = true;
```

or add `pkgs.aurora-diag` to `environment.systemPackages`. The flake
also exposes it as `packages.aarch64-linux.diag`. The package carries
Textual for the dashboard and puts alsa-utils, glib, vulkan-tools,
mesa-demos, iw, smartmontools and bluez after the system's own `PATH`,
so every section works as on Fedora (`dnf install aurora-diag`) and ALARM
(`pacman -S aurora-diag`), which package the same commit. The build runs
the upstream `make check` suite and an installed smoke test.

## Updating the pin

`sources.json` pins the commit, version and hashes of the GitHub
archive. To move to a new commit, set `commit`, `version`, `source_url`,
`archive_root`, `sha256` and `nix_hash` there; the recipe in
`pkgs/aurora-diag.nix` reads all of them. `nix_hash` is the SRI form of
`sha256`, the hash of
`https://codeload.github.com/aurora-silicon/aurora-diag/tar.gz/<commit>`.
