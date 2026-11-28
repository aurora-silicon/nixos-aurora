# aurora-audio

Aurora Apple Silicon audio profiles for PipeWire and WirePlumber: built-in
microphone DSP graphs, headphone jack and built-in card routing rules, and
period-interrupt scheduling for speaker PCMs.

## Speaker protection (speakerguardd v2 by default)

Built-in speakers on every Mac are protected and voiced by **speakerguardd v2**
(`speakerguardd-v2`), compiled from the Mac's own Apple tuning bundle fetched
from the pinned macOS restore image by `aurora-speaker-upgrade`. No Asahi
speaker DSP graphs, speaker FIRs, or WirePlumber raw speaker volume lock are
installed.

Existing installations migrate to `speakerguardd-v2` automatically on package
upgrade: `aurora-audio` pulls `speakerguardd-v2` and `aurora-speaker-upgrade`,
retires legacy Aurora speaker protection builds, and runs
`aurora-speaker-stack migrate --on-upgrade` to mask legacy units and enable
the v2 presets.

## Optional user opt-out (`aurora-speaker-stack`)

Users who explicitly choose to run `speakersafetyd` instead of `speakerguardd`
v2 can switch with one command:

```sh
sudo aurora-speaker-stack select speakersafetyd
```

This checks kernel support and installs `speakersafetyd` first, then masks the
v2 and upgrade units, switches the kernel interlock, records the choice in
`/etc/aurora/speaker-stack.conf`, installs a root `ExecStartPre` drop-in on
`speakersafetyd.service` (`aurora-speaker-stack interlock-apply`) so the
per-bind kernel interlock is armed on every boot, and starts
`speakersafetyd.service`. Later package upgrades read
`/etc/aurora/speaker-stack.conf` and preserve the user's choice. If package
installation, interlock switching, or service startup fails, the prior `sgv2`
state is kept or restored and the command exits non-zero.

Because `aurora-audio` no longer ships the Asahi speaker DSP graphs, speaker
FIRs, or the WirePlumber raw speaker volume lock, opting into stock
`speakersafetyd` runs without those Asahi speaker profiles unless you supply
them separately.

To check the active selection or switch back to `speakerguardd` v2:

```sh
aurora-speaker-stack status
sudo aurora-speaker-stack select sgv2
```

See `man 8 aurora-speaker-stack` for all options.
