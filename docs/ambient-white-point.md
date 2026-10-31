# Opt-in ambient white point draft

This package carries the ambient policy patch against GSD 50.1. It is a draft
for review and hardware qualification, with no deployment or feed publication.

## Compositor validation

Mutter 50.4 consumes the existing GSD Temperature property but its
white point implementation requires an assigned color profile and a gamma LUT.
Its `NightLightSupported` check is gamma-only. CTM-only outputs are unsupported
on this base. This draft does not force the capability flag or claim a J616s
output shift on an unsupported path.

The public GNOME Mutter 50.4 tag was inspected in
`src/backends/meta-color-manager.c`, `meta-color-device.c`,
`meta-monitor-manager.c` and
`data/dbus-interfaces/org.gnome.Mutter.DisplayConfig.xml`.
It subscribes to `notify::temperature` on GSD Color and accepts 1000-10000 K.
Source validation does not establish a working sensor or display response.

The GSettings key `org.gnome.settings-daemon.plugins.color ambient-white-point-enabled`
defaults to `false`. No schema override enables it. The package keeps the normal
color service and adds no daemon, privileged helper or sysfs permissions.
The optional CLI is a documentation file, outside PATH. Run it with `sh` or copy
it to a user bin directory. GSettings works without the CLI.

Exactly one readable IIO `in_colortemp_raw` channel is required. Kelvin is
`(raw + offset) * scale`, with absent offset and scale defaulting to 0 and 1.
Illuminance, die temperature and vendor RGB channels are never substitutes.
Samples must be 1000-10000 K, targets are 4000-6500 K, the deadband is 50 K,
and each five-second sample changes the target by at most 100 K. Reads are
asynchronous and expire after 15 seconds, including suspend time. Opt-out,
invalid readings and compositor loss clear the sample. Night Light schedule,
preview and its return to neutral take priority. A manual Temperature write
pauses ambient adaptation until an off/on toggle. There is no per-panel or HDR
guarantee. The compositor temperature property can affect multiple displays.

## Hardware lane qualification

These are proposed steps for a separately authorized hardware run on J616s.
No target has been accessed or deployed by this draft. Retain the previous package
or NixOS generation before installation. Do not publish device paths, serials,
private logs or user settings in the PR.

After the distribution-specific install below, restart the normal color service
from the GNOME user's environment.

```sh
systemctl --user restart org.gnome.SettingsDaemon.Color.service
schema=org.gnome.settings-daemon.plugins.color
mkdir -p ambient-rollback
gsettings get "$schema" ambient-white-point-enabled > ambient-rollback/ambient-enabled
gsettings get "$schema" night-light-enabled > ambient-rollback/night-enabled
gsettings set "$schema" ambient-white-point-enabled false
```

Read the real sensor through IIO with the same ordinary permissions as GSD.
This reports channel counts and Kelvin values without writing sysfs or changing
permissions. Missing, ambiguous or unreadable CCT means the sensor path is
unqualified. Record that result and continue the supported fallback checks.

```sh
python3 - <<'PYTHON'
from pathlib import Path
import math
channels = list(Path('/sys/bus/iio/devices').glob('iio:device*/in_colortemp_raw'))
print('CCT channel count', len(channels))
for channel in channels:
    try:
        def value(name, default):
            p = channel.parent / name
            return float(p.read_text()) if p.exists() else default
        scale = value('in_colortemp_scale', 1)
        kelvin = (float(channel.read_text()) + value('in_colortemp_offset', 0)) * scale
        print('Kelvin', kelvin, 'valid', scale > 0 and math.isfinite(kelvin) and 1000 <= kelvin <= 10000)
    except (OSError, ValueError) as error:
        print('CCT unavailable', type(error).__name__)
PYTHON
gdbus call --session --dest org.gnome.Mutter.DisplayConfig \
  --object-path /org/gnome/Mutter/DisplayConfig \
  --method org.freedesktop.DBus.Properties.Get \
  org.gnome.Mutter.DisplayConfig NightLightSupported
```

With Night Light disabled, enable ambient and monitor the published properties.

```sh
gsettings set "$schema" night-light-enabled false
gsettings set "$schema" ambient-white-point-enabled true
gdbus monitor --session --dest org.gnome.SettingsDaemon.Color \
  --object-path /org/gnome/SettingsDaemon/Color
```

Under two steady lighting conditions, read back the channel and use
`org.freedesktop.DBus.Properties.GetAll org.gnome.SettingsDaemon.Color` on the same
object. Allow several five-second samples. When a valid single sensor and
compositor support are present, expect Available and Active true, Temperature
moving within 4000-6500 K in at most 100 K steps, and a measured or visible output
shift with Night Light off. A 6500 K sample need not produce a shift. If support
is false, verify Active remains false and output stays at normal Night Light
policy. A D-Bus change alone is not proof of a display shift.

Exercise preview while ambient is enabled.

```sh
gdbus call --session --dest org.gnome.SettingsDaemon.Color \
  --object-path /org/gnome/SettingsDaemon/Color \
  --method org.gnome.SettingsDaemon.Color.NightLightPreview 20
```

Expect ambient Active false throughout preview and its return to neutral. It
must restart from neutral afterwards. Also exercise a real Night Light schedule,
manual Temperature pause, opt-out restoration, sensor removal or read failure,
compositor restart, suspend/resume and mixed displays in the hardware lane.
The included fixture and private-bus tests cover these policy/lifecycle failure
paths without hardware. Do not simulate a real sensor by changing production
sysfs paths.

Before package rollback, stop adaptation and restore the saved settings.

```sh
gsettings set "$schema" ambient-white-point-enabled false
gsettings set "$schema" night-light-enabled "$(cat ambient-rollback/night-enabled)"
```

Restore the prior package or generation using the distribution commands below,
then restart `org.gnome.SettingsDaemon.Color.service`. Keep the feature off while
the draft is removed. If retaining the draft after a test, restore the saved
ambient boolean explicitly. No ICC profile or other color preference needs
resetting.

## NixOS package steps

The overlay extends the repository's locked nixpkgs GSD 50.1 derivation and
retains its existing patches, dependencies and install checks. The current
nixos-unstable recipe also uses 50.1. The color test suite is enabled, with
`dbus-daemon` present for its private bus. The flake exposes
`packages.aarch64-linux.gnome-settings-daemon` for CI and package review.

```sh
nix build --no-link --print-build-logs .#gnome-settings-daemon
```

On a separately authorized NixOS J616s, apply this PR revision to the flake used
by the existing GNOME configuration. Preserve that configuration's other modules.
Save the previous generation and activate with `test`, without setting a new
boot default. Here `GNOME_FLAKE` is the reviewed system flake containing that
machine's existing configuration plus this overlay.

```sh
mkdir -p ambient-rollback
readlink -f /run/current-system > ambient-rollback/system
sudo nixos-rebuild test --flake "$GNOME_FLAKE"
```

For the repository's image configuration itself, the explicit flake selector is
`.#aurora-gnome`. Do not substitute that image configuration for an installed
machine's existing configuration. The optional helper is in
`$(nix build --no-link --print-out-paths .#gnome-settings-daemon)/share/doc/gnome-settings-daemon/gnome-ambient-white-point`.
After the common settings rollback above, activate the exact previous system.

```sh
sudo "$(cat ambient-rollback/system)/bin/switch-to-configuration" test
systemctl --user restart org.gnome.SettingsDaemon.Color.service
```
