# speakerguardd v2

speakerguardd v2 is the only speaker protection on every Mac, and the only
program that takes the kernel's speaker interlock. The Asahi stack is gone:
the Aurora platform always enables `aurora.speakerguardd.v2` and
`aurora.speakerguardd.upgrade`, speakersafetyd and speakerguardd 0.1 are no
longer packaged (nixos-apple-silicon's sound module still names
speakersafetyd: the overlay ships it empty and `speakersafetyd.service` is
masked), and asahi-audio 4.1-aurora18 installs no Asahi speaker graph. The
next `nixos-rebuild switch` drops the old units.

`aurora-speaker-upgrade` moves a Mac's speakers to v2 with that Mac's own
tuning:

```sh
sudo aurora-speaker-upgrade --check    # dry run: collect, compile and self-check; nothing stored or switched
sudo aurora-speaker-upgrade            # switches only if this Mac's self-check passes
sudo aurora-speaker-upgrade status
```

The `aurora-speaker-upgrade` boot unit runs the same switch at boot without
a prompt, and moves only a speaker whose protected playback rows are on
record; a refusal is recorded and not retried until the kernel,
speakerguardd v2 or the tool changes. A Mac that v2 does not qualify keeps
its speakers at the kernel's floor by default.

## Optional user opt-out (`aurora-speaker-stack`)

Users who explicitly choose to run `speakersafetyd` instead of speakerguardd v2
can opt out declaratively in their NixOS configuration:

```nix
aurora.speakers.stack = "speakersafetyd";
```

or run the one-command helper:

```sh
sudo aurora-speaker-stack select speakersafetyd
```

This disables `aurora.speakerguardd.v2` and `aurora.speakerguardd.upgrade`,
adds `pkgs.speakersafetyd-nixpkgs` systemd and udev packages, installs the
privileged `aurora-speaker-stack interlock-apply` `ExecStartPre` drop-in on
`speakersafetyd.service` so the per-bind kernel interlock is armed on every
boot, and writes `/etc/aurora/speaker-stack.conf` so upgrades preserve the
opt-out.

Because `asahi-audio` no longer installs the Asahi speaker DSP graphs, speaker
FIRs, or WirePlumber raw speaker volume lock, opting into stock
`speakersafetyd` runs without those Asahi speaker profiles unless supplied
separately.

To inspect the current state or return to speakerguardd v2:

```sh
aurora-speaker-stack status
sudo aurora-speaker-stack select sgv2
```

See `man 8 aurora-speaker-stack`.
