# Apple Silicon power-profile parity

This distribution uses power-profiles-daemon (PPD), rather than Fedora's
tuned-ppd. The current PPD Apple path has no Apple CPU/platform-profile driver.
Its placeholder path provides no equivalent CPU performance tuning and does
not pin the CPUs at their maximum frequency. Available profile names alone
do not establish hardware support; generic PPD actions may still apply.
No governor override, tuned profile or CPU frequency floor is added here.

The Fedora regression motivating this audit was measured on a Neo, Fedora 45,
AC, settled desktop, with 120-second idle samples:

| TuneD profile | Idle power | 20 s single-thread count | 20 s all-thread count |
| --- | ---: | ---: | ---: |
| balanced | 3476 mW | 2615 | 7152 |
| powersave | 3475 mW | 2648 | 7059 |
| throughput-performance | 4953 mW | 2668 | 6881 |
| balanced (repeat) | 3493 mW | 2747 | 7138 |

These integer-loop counts are baseline observations, not stress-ng results.
Fedora's GNOME Performance mapping selected `throughput-performance`, whose
`performance` governor pinned CPU clocks: +1477 mW (1.48 W, 42%) idle power,
without a measured throughput gain. Fedora's `aurora-platform-core` fix maps
the stock Performance entry to `aurora-performance`, replacing the CPU section
with `schedutil` and removing inherited boost writes. Stock tuned per-policy
boost writes also fail with EINVAL on M2. That tuned-specific migration does
not apply to PPD here.

## Power Saver

Power Saver gets a CPU power budget from `aurora-power-budget`, built from
[aurora-platform](https://github.com/aurora-silicon/aurora-platform/blob/main/power/README.md)
and packaged here as `pkgs.aurora-power-budget` with the `aurora.powerBudget.enable` option (default: on wherever power-profiles-daemon is enabled).
Like macOS Low Power Mode it is a short-window
budget, not a fixed frequency table: while the profile daemon reports
`power-saver`, every 100 ms the budget (the device tree energy model's power
for every CPU at 0.45 x its cluster maximum) is spent on the frequency steps
that buy the most CPU capacity per milliwatt, and each cluster is capped with
`scaling_max_freq`; the biggest cores are also held at 0.64 x their maximum,
as macOS holds one busy P core. Thermal limits still win; the governor stays
`schedutil`. Balanced and Performance are
untouched, and outside Power Saver the daemon only waits on D-Bus. The GPU,
ANE, display and fan legs of Low Power Mode are not covered yet. Measurements
are in the aurora-platform README. Performance is still never mapped to the
`performance` governor.

## PWR acceptance plan

Before merging, record the installed PPD version, `powerprofilesctl list`,
reported driver, available profiles and each CPU policy's governor, min/max,
current frequency and boost state. Select each supported profile and verify
that no performance governor or new frequency floor appears. If Performance
is unavailable on the placeholder driver, record it as unavailable.

On the Neo, use matched AC/brightness/background-workload conditions and repeat
settled 120-second idle-power samples per profile, ending on Balanced. Compare
Fedora's candidate Performance with Balanced; separately record this distro's
placeholder behavior. Repeat identical stress-ng `--cpu 1 --cpu-method int64
--timeout 60s --metrics-brief` and `--cpu 0` runs per supported profile, recording
bogo-ops/s, temperature, clocks and throttling. Restore the original profile.
On M2 verify no new boost writes or changed kernel boost policy. These docs
make no claim that a package-power budget or performance boost exists.

PWR owns hardware qualification and merging. This parity PR changes only
documentation and is left unmerged. Fedora's design, transaction tests and
rollback are documented in
[fedora-aurora power profiles](https://github.com/aurora-silicon/fedora-aurora/blob/main/docs/power-profiles.md).
