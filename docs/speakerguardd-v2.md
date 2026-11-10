# speakerguardd v2

speakerguardd v2 is installed beside the legacy protection (speakersafetyd,
speakerguardd 0.1), which stays installed and keeps the speakers until a
switch, and keeps any Mac whose self-check refuses:

```sh
sudo aurora-speaker-upgrade --check    # dry run: collect, compile and self-check; nothing stored or switched
sudo aurora-speaker-upgrade            # switches only if this Mac's self-check passes
sudo aurora-speaker-upgrade status
sudo aurora-speaker-upgrade --revert   # back to the legacy protection (--purge also removes the stored tuning)
```

The `aurora-speaker-upgrade` boot unit runs the same switch at boot without
a prompt; a refusal is recorded and not retried until the kernel,
speakerguardd v2 or the tool changes.
