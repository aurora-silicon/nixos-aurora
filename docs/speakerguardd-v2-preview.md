# speakerguardd v2 (preview)

speakerguardd v2 is a preview. It does not fully match macOS yet. The legacy
protection (speakersafetyd, speakerguardd 0.1) is the supported default and
stays installed. To go back at any time: sudo aurora-speaker-upgrade --revert.

speakerguardd v2 is installed only on request, beside the legacy protection,
and the legacy protection keeps the speakers until you switch:

```sh
sudo aurora-speaker-upgrade --check    # dry run: collect, compile and self-check; nothing stored or switched
sudo aurora-speaker-upgrade            # shows this notice, asks, then switches only if the self-check passes
sudo aurora-speaker-upgrade status
sudo aurora-speaker-upgrade --revert   # back to the legacy protection (--purge also removes the stored tuning)
```

Without a terminal (scripts, the `aurora-speaker-upgrade` boot unit) a switch
needs `--i-understand-preview`; without it the tool exits 2 and changes
nothing. Enabling the boot unit alone switches nothing while v2 is a preview.
