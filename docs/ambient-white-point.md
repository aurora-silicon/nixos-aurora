# Ambient white point

On a Mac whose ambient light sensor reports the colour of the light, the display white point can follow the room, the way True Tone does on macOS. Under a warm lamp the screen gets a little warmer, in daylight it stays neutral. It is off by default and it is your choice to turn it on.

## How it works

Three pieces, each in the standard place for it.

1. The kernel reports the light's correlated colour temperature as the documented IIO channel `in_colortemp_input`, next to `in_illuminance_input`.
2. iio-sensor-proxy, which GNOME and KDE already use for automatic brightness, reads it and publishes it on D-Bus as `ColorTemperature` (kelvin, 0 when the sensor has no colour channel). It is updated while a program holds the light sensor with `ClaimLight`, like `LightLevel`.
3. The desktop picks a white point and applies it through its existing Night Light path. On GNOME that is the colour plugin of gnome-settings-daemon, which publishes the temperature that mutter applies. On KDE it is KWin's Night Light, which sets the screens' channel factors. Nothing writes to the display behind the compositor's back.

## The model

The display white point, as a colour temperature, follows half of the ambient light's shift away from 6500 K, measured in mired (one million divided by kelvin, where equal steps look about equally large).

* It never goes warmer than 5000 K and never cooler than 6500 K, the panel's native white.
* Below 15 lux the adaptation fades out, and at 10 lux or less it is off. In a dark room the screen is the main light and the sensor's colour reading gets noisy. There is no cut-off in bright light. These lux points are the ones macOS uses.
* A 10 second median filter ignores short changes, such as a shadow or a phone screen near the sensor, so a real change in the room shows up about 5 seconds later.
* Turning it on or off fades over 2 seconds, and a change in the room fades over 5 seconds, whatever the size, with the same easing curve macOS uses. These are the macOS True Tone timings on the M4 Pro.
* Small changes under 2.5 mired are ignored so the screen doesn't wander.

For example, at 250 lux under 5050 K light it settles near 5700 K, at 600 lux under 5400 K daylight near 5900 K, and under 2700 K or 4000 K lamps at the 5000 K limit.

The lux points, fade times and fade shape come from macOS on the M4 Pro. How much it adapts is a starting value until macOS has been measured under changing light. macOS adapts in two dimensions with a Bradford matrix; this follows the colour temperature only, through Night Light's per-channel scale. The GNOME and KDE code share the same test vectors, so both desktops behave the same.

## Night Light

Night Light always wins. The screen gets the warmer of the two temperatures, so the ambient white point can never make the screen bluer than Night Light asks for, and the hand-over at sunset is smooth. That holds during a Night Light preview too, so a preview's fade starts from what is on screen.

## Turning it on

GNOME:

```
gsettings set org.gnome.settings-daemon.plugins.color ambient-white-point-enabled true
```

KDE Plasma:

```
kwriteconfig6 --notify --file kwinrc --group NightColor --key AmbientWhitePoint true
```

KWin picks the change up right away. Set either back to `false` to turn it off. aurora-diag has a live demo with the sensor reading, the chosen white point and a toggle (`aurora-diag demo whitepoint`).

## Checking it

Ambient reading, while something holds the light sensor:

```
busctl get-property net.hadess.SensorProxy /net/hadess/SensorProxy net.hadess.SensorProxy ColorTemperature
```

GNOME state:

```
busctl --user get-property org.gnome.SettingsDaemon.Color /org/gnome/SettingsDaemon/Color org.gnome.SettingsDaemon.Color Temperature
busctl --user get-property org.gnome.SettingsDaemon.Color /org/gnome/SettingsDaemon/Color org.gnome.SettingsDaemon.Color AmbientWhitePointActive
```

`AmbientWhitePointAvailable`, `AmbientColorTemperature` and `AmbientWhitePointTemperature` are on the same interface.

KDE state:

```
busctl --user get-property org.kde.KWin.NightLight /org/kde/KWin/NightLight org.kde.KWin.NightLight appliedTemperature
```

`ambientWhitePointEnabled`, `ambientWhitePointAvailable`, `ambientWhitePointActive`, `ambientColorTemperature` and `ambientWhitePointTemperature` are on the same interface.

## Requirements and limits

* A light sensor with a colour channel. On Apple silicon that is the AOP light sensor on the M1 Pro, M2 and M4 Pro machines with a kernel that reports `in_colortemp_input`. The Neo's sensor reports lux only, so nothing changes there.
* A compositor that can apply Night Light to the display. mutter 51 and KWin apply it through the CRTC colour matrix when the display has no gamma table. mutter 50 needs a gamma table, so GNOME on mutter 50 can't shift a display that only has the colour matrix, for Night Light or for this.
* The white point is applied as Night Light's per-channel scale, a simple approximation of the Bradford adaptation macOS uses.
* One setting covers every display, as with Night Light.

## Packages

The overlay patches `iio-sensor-proxy` (3.9), `gnome-settings-daemon` (50.1) and `kdePackages.kwin` (6.7.5), so every Aurora NixOS system gets them with no option to set. The GNOME colour plugin tests run in the build (`gcm-self-test`, `ambient-policy`, `ambient-service`). The packages are exposed as `iio-sensor-proxy`, `gnome-settings-daemon` and `kwin` in the flake. Fedora and Arch Linux ARM carry the same patches.
