# ANE diagnostics

The optional `aurora-diag` package provides `aurora-diag ane --json`,
`aurora-diag check --only ane --no-api --json`, the report ANE section and
an ANE dashboard tab. It reads driver binding, live DT status/compatible,
H13/H14/H16/H17 generation, busy nanoseconds, completed jobs, wedged state,
runtime PM and optional requested performance level/memory bandwidth and
transition errno. It never opens the accelerator or submits a workload.

All three Aurora distributions pin the same 0.2.1 source revision and run
the same synthetic sysfs fixture suite during package checks. Install with
`dnf install aurora-diag` on Fedora, `pacman -S aurora-diag` on ALARM, or add
`pkgs.aurora-diag` to NixOS `environment.systemPackages`. This package is
opt-in and does not change device access or install firmware.

Source access must be available to the build service before release; the
pin disables source-cache redistribution. No credentials belong in package
recipes or source pins.
