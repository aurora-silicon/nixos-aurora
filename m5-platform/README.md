# aurora-m5-platform-config

Deep sleep on the MacBook Pro (M5 Pro, J714s). The package is installed on every Mac and does
nothing on any Mac other than the J714s: the unit is skipped by `ConditionFirmware`, and the hook
returns at once when the device tree does not name `apple,j714s`.

It needs a kernel whose T6050 sleep driver binds on the J714s (`apple,t6050-sleep`,
aurora-silicon/linux integration e0ee46a1 or later) and an aura Stage 2 that gives the sleep
controller its wake sources (aura#214, 76f6d953).

## What it sets on the J714s

- **Deep sleep only.** `aurora-m5-sleep-policy.service` writes
  `/run/systemd/sleep.conf.d/90-aurora-m5-deep.conf`: `SuspendState=mem`,
  `MemorySleepMode=deep`. A kernel without the sleep driver offers only s2idle, and the Mac then
  does not suspend at all rather than try s2idle.
- **The lid suspends** on battery, on AC and docked:
  `/run/systemd/logind.conf.d/90-aurora-m5-lid.conf`. Plasma (PowerDevil) and GNOME handle the lid
  themselves while they run, with their own settings. Plasma's default keeps a docked Mac awake
  with the lid closed.
- **A safety RTC alarm.** The T6050 sleep driver refuses a sleep unless the PMU RTC alarm is armed.
  `/usr/lib/systemd/system-sleep/50-aurora-m5-rtc-safety` arms one `SAFETY_S` seconds ahead
  (`/etc/aurora-m5-sleep.conf`, default 3600, the RTC driver's limit) before a suspend that has
  none, and clears it after the wake if it is still pending. An alarm armed by someone else
  (`rtcwake`, a test) is kept. With the lid still closed after a safety wake, logind suspends
  again. The hook logs with the tag `aurora-m5-sleep` (`journalctl -t aurora-m5-sleep`).

`suspend.target` and `sleep.target` must not be masked; the distribution does not mask them.

## Overriding

- A file of the same name in `/etc/systemd/sleep.conf.d/` or `/etc/systemd/logind.conf.d/`
  replaces the one under `/run`.
- `systemctl mask aurora-m5-sleep-policy.service` keeps systemd's defaults from the next boot.
- The policy is written at boot. After installing the package on a running Mac, the sleep
  setting applies at the next suspend and the lid setting after the next boot.

## Known issues (2026-11-20)

- A sleep entered right after a USB-C event on a Dell monitor's port can hang before the commit,
  in about 1 in 10 such sleeps; the watchdog restarts the Mac about 2 minutes later.
- The Dell monitor's SuperSpeed hub can be missing after about 15 % of boots. It comes back after
  the first sleep.
- A stray Wi-Fi/Bluetooth wake right after the sleep's entry is taken as a dark wake: user space
  stays frozen and the Mac sleeps again.
