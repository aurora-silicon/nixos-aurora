# UPower 1.91.5 candidate: install, verify, rollback

The Aurora fork carries the macsmc kernel time-estimate fix on upstream 1.91.5.
It adds no public D-Bus fields: `TimeToEmpty` and `TimeToFull` use positive kernel
estimates for the matching battery state, including at zero instantaneous rate.
Invalid/missing estimates retain upstream's rate-based fallback; other supply
drivers retain upstream behavior. Capacity, cycles and charge thresholds are
upstream properties. Upstream 1.91.5 also prefers live charge thresholds over
hwdb defaults. This package sets no charging policy.

## Fedora 45 lead install

Use the `upower-fedora45` artifact from the successful **UPower Fedora 45** PR
workflow, not the Fedora 44 RPM workflow. These are review artifacts; publication
and signing are separate from this PR. Review the workflow/source revision and
artifact hashes before installing unsigned candidate RPMs.

```sh
# Set RUN to the successful Fedora 45 run linked from the packaging PR.
gh run download "$RUN" --repo aurora-silicon/fedora-aurora \
  --name upower-fedora45 --dir upower-candidate
rpm -q upower upower-libs upower-devel
rpm -qp --qf '%{NAME} %{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' \
  upower-candidate/out/rpms/upower*.rpm
sudo dnf install ./upower-candidate/out/rpms/upower*.rpm
sudo systemctl restart upower.service
rpm -q --qf '%{NAME} %{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' upower upower-libs
upower --version
upower -d
```

The expected Aurora EVR is `1:1.91.5-1.fc45.aurora`; all installed UPower
subpackages must come from the same build. Epoch 1 outranks stock Fedora's
Epoch 0 even when both use Version 1.91.5. The test workflow performs a real DNF
upgrade from stock and a rollback in separate disposable Fedora 45 packaging
state; it also checks configuration and persisted threshold choice survive.

## Read-only battery verification (all distributions)

```sh
battery=$(upower -e | sed -n '/\/battery_/ {p;q;}')
test -n "$battery"
upower -i "$battery"
busctl get-property org.freedesktop.UPower "$battery" org.freedesktop.UPower.Device TimeToEmpty
busctl get-property org.freedesktop.UPower "$battery" org.freedesktop.UPower.Device TimeToFull
for field in Model EnergyFullDesign EnergyFull Capacity ChargeCycles \
             ChargeThresholdSupported ChargeThresholdEnabled ChargeStartThreshold ChargeEndThreshold; do
  busctl get-property org.freedesktop.UPower "$battery" org.freedesktop.UPower.Device "$field"
done
for field in status time_to_empty_now time_to_full_now power_now current_now \
             charge_full_design charge_full cycle_count \
             charge_control_start_threshold charge_control_end_threshold; do
  path=/sys/class/power_supply/macsmc-battery/$field
  if test -r "$path"; then printf '%s=' "$field"; cat "$path"; fi
done
```

While discharging, a positive `time_to_empty_now` should match `TimeToEmpty`
(seconds), even when rate is zero. While charging, compare `time_to_full_now`
with `TimeToFull`; the opposite estimate is zero. At full charge both can be
zero. Live estimates change between reads. Absence of a kernel attribute is not
a packaging failure. `charge_full*` is reported in microamp-hours by sysfs;
UPower converts charge to energy using design voltage. Capacity is the full to
design ratio in percent. Threshold support depends on the kernel driver and
hwdb; do not enable thresholds just to verify reporting. Preserve user choices.

## Fedora rollback to stock

```sh
# Restrict to stock repos: otherwise Aurora's epoch wins the solver again.
# Include upower-devel only if it is installed.
sudo dnf --repo=fedora --repo=updates distro-sync upower upower-libs upower-devel
sudo systemctl restart upower.service
rpm -q --qf '%{NAME} %{EPOCHNUM}:%{VERSION}-%{RELEASE}\n' upower upower-libs
upower -d
```

Review the transaction before accepting it. Stock must show Epoch 0. Config and
`/var/lib/upower/charging-threshold-status` are retained. With an enabled Aurora
repository, a future full upgrade selects the fork again; exclude these package
names locally if remaining on stock is intentional. Do not package that choice.

## Distribution parity

| Distribution | Package | Source version | Upgrade / rollback |
| --- | --- | --- | --- |
| Fedora 45 | `upower`, `upower-libs`, `upower-devel` | 1.91.5, pinned Aurora revision | Epoch 1 / stock-repo distro-sync |
| Arch Linux ARM | `upower-aurora` providing `upower=1.91.5` | Same revision and archive SHA-256 | Provider replacement / explicit stock provider |
| NixOS | overlay `upower` | Same revision and archive SHA-256 | System generation / previous generation |

After publication, ALARM upgrades with `sudo pacman -Syu upower-aurora`; review
replacement of stock `upower` if present. Roll back with `sudo pacman -S extra/upower`
(and accept removal of the conflicting Aurora provider). Restart `upower.service`
and use the read-only checks above. Do not use `--overwrite` or skip dependency checks.

On NixOS, update the configuration's pinned `nixos-aurora` input to the reviewed
packaging revision, then `sudo nixos-rebuild switch --flake .#HOST`. Keep the old
lock file/generation. Roll back with `sudo nixos-rebuild switch --rollback` and
restore the old input lock before the next rebuild. Inspect
`readlink -f /run/current-system/sw/bin/upower` and run the same read-only checks.

No fleet installation or hardware verification is performed by these PRs.
