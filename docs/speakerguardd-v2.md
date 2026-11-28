# speakerguardd v2

`speakerguardd-v2` is the default speaker protection and voicing stack on all
Aurora NixOS installations (`aurora.speakers.stack = "sgv2"`). Legacy Asahi
speaker DSP graphs, `speakerguardd` 0.1, and `speakersafetyd` are removed from
the default system, and `aurora-speaker-upgrade.service` migrates existing Macs
at boot using the pinned macOS restore image's tuning and the Mac's own
calibration:

```sh
sudo aurora-speaker-upgrade --check    # dry run: collect, compile and self-check; nothing stored or switched
sudo aurora-speaker-upgrade            # switches only if this Mac's self-check passes
sudo aurora-speaker-upgrade status
```

## User opt-out (`aurora-speaker-stack`)

Users who explicitly want `speakersafetyd` instead of `speakerguardd` v2 can
opt out declaratively in their NixOS configuration:

```nix
aurora.speakers.stack = "speakersafetyd";
```

Or run the one-command helper:

```sh
sudo aurora-speaker-stack select speakersafetyd
```

This records the choice in `/etc/aurora/speaker-stack.conf` and
`/etc/nixos/aurora-speaker-stack.nix` and disables `speakerguardd-v2` and
`aurora-speaker-upgrade` in favor of `speakersafetyd`, preserved across future
upgrades. To inspect status or return to `speakerguardd` v2:

```sh
aurora-speaker-stack status
sudo aurora-speaker-stack select sgv2
```

See `man 8 aurora-speaker-stack` for details.
