# Updates and releases

## Installed systems

Factory images write `/etc/nixos/flake.nix` and lock the Aurora input to the
image's source commit. The default input follows `channel-testing`; images can
also follow `channel-stable` or remain pinned. Rebuilds start from those locked
inputs and include the machine's current `machine.nix` and `owner.nix`.

Take the newest update from the configured channel:

```sh
sudo aurora-update
```

On factory images this updates the `aurora` input and runs `nixos-rebuild switch
--flake /etc/nixos#aurora`. Other consumer flakes should declare their source in
the installed configuration:

```nix
aurora.update.flake = "/home/owner/nixos#macbook";
```

Set `aurora.update.inputName` if the input has a name other than `aurora`.
The flake must have a writable local lockfile. A reference without `#CONFIG`
uses the host name as its configuration selector, like `nixos-rebuild`.

You can also select a source explicitly:

```sh
sudo aurora-update --flake '/home/owner/my flake#macbook'
```

After a successful local activation, this command remembers the canonical
source for that exact `/run/current-system` target. Selection order is explicit
`--flake`, matching-generation memory, `aurora.update.flake`, then the factory
`/etc/nixos#aurora` fallback when `aurora.imageLayout` is set. Other systems do
not guess a source. Additional arguments pass to `nixos-rebuild switch`; remote
switches do not create local source memory.

NixOS does not retain the consumer reference from a direct `nixos-rebuild`
invocation. Declare `aurora.update.flake` for that workflow; a direct rebuild
or rollback to another generation cannot inherit unrelated remembered state.
To apply local configuration changes without updating the factory lock:

```sh
sudo nixos-rebuild switch --flake /etc/nixos#aurora
```

Nothing updates unattended. The Aurora module configures the signed cache at
`https://aurorasilicon.org/nixos-aurora/cache` and trusts `keys/cache.pub`;
`cache.nixos.org` remains available. Channel refs advance after the live cache
covers that commit's hardware outputs, so installed systems can substitute them.

### Stage 2 on rebuild

`nixosModules.installed` refreshes `m1n1/boot.bin` on the ESP during bootloader
installation (`nixos-rebuild switch` or `boot`). The checked payload contains the
system's Aura build, kernel device trees and U-Boot. Required boards default to
`j700`, `j616s` and `j614s` through `aurora.stage2.requiredBoards`.

An unchanged payload is left alone. A changed payload is staged, verified and
renamed into place, preserving the previous file as `m1n1/boot.bin.old`. The
installer checks the input digest, the mounted FAT ESP and, when available, the
booted ESP's partition identity. A failed check stops installation. Stage 1 is
never written by a rebuild.

Set `aurora.stage2.enable = false;` to stop Stage 2 updates. The upstream
unchecked copy stays excluded, so disabling updates leaves the ESP payload alone.

For a kernel regression, select the previous NixOS generation in GRUB. If
Stage 2 itself prevents booting, restore `m1n1/boot.bin.old` over
`m1n1/boot.bin` from macOS or the recovery environment.

### Moving an existing install to the channel (one-time)

Images before Alpha 10 used an exact-commit input. To follow testing:

```sh
sudo sed -i 's|github:aurora-silicon/nixos-aurora/[0-9a-f]\{40\}|github:aurora-silicon/nixos-aurora/channel-testing|' /etc/nixos/flake.nix
sudo nix flake update aurora --flake /etc/nixos
sudo nixos-rebuild switch --flake /etc/nixos#aurora
```

The first switch installs `aurora-update` and the checked Stage 2 updater;
later updates use `sudo aurora-update`.

## Channels and cache publication

One cumulative cache serves both channels. Deploying a cache release can advance
`channel-testing`; `promote.yml` advances `channel-stable` after its approval,
soak-time and signed-cache coverage checks. The `channels` branch records the
live release and channel history in `channels.json`.

Build jobs export **unsigned** candidate caches. Collection checks eligible source
commits and artifact digests, verifies build attestations where emitted, requires
exact derivations and output sets, and verifies NAR contents. The protected `testing-signing` job signs only
verified narinfo metadata. Publication verifies signatures and NARs before
creating an immutable release; deployment verifies the release provenance,
target-commit coverage and every signed NAR over HTTP before serving it.

Module-only changes can reuse existing signed metadata and immutable NAR URLs
without a signing key. The new release records the new source commit and its
complete hardware coverage. An already-published commit can be deployed later
without publishing again. Stale queued commits cannot replace newer published
or served commits. Keep older cache releases available: newer metadata can
continue to reference their NAR assets.

Deployment and promotion reject backward cache or channel commits unless an approved
rollback uses `allow-downgrade=true`. The selected cache must still cover every
unchanged channel; if an older snapshot lacks stable's outputs, use a cumulative
snapshot containing both rather than replacing the live cache with it.

## Maintainer workflows

| Workflow | Use |
| --- | --- |
| `track-sources.yml` | Every 30 minutes with `TRACK_SOURCES`, or manually. Plans source updates; optional live mode opens proposals, dispatches checks and mirrors allowed archives. `AUTO_MERGE_SOURCES` enables eligible automatic merges. FEX updates refresh selected submodule gitlinks; incomplete refreshes require review. |
| `checks.yml` | Push, PR or manual builds. Empty manual `packages` builds every exported package; an explicit list selects packages. Exports unsigned candidates and build attestations. |
| `publish-cache.yml` | Manual, after a successful main build, or every six hours with `AUTO_PUBLISH_TESTING`. Collects and publishes a signed snapshot, or reuses existing signed outputs. `deploy=yes` or `AUTO_DEPLOY_TESTING` activates it. |
| `deploy-cache.yml` | Verifies a cache release and builds documentation in parallel, then deploys one Pages site. `advance-testing=false` leaves the channel ref unchanged; an intentional downgrade uses `allow-downgrade=true` and the `stable-promotion` environment. |
| `promote.yml` | Promotes a tested commit through `stable-promotion`; `STABLE_MIN_SOAK_HOURS` sets the minimum soak interval. |
| `images.yml` | Builds a selected profile and checked Stage 2. `AUTO_IMAGES` requests all profiles after testing advances to main; `channel` selects the generated configuration's update channel. |
| `publish-payload.yml` | Manually publishes a signed installer payload from a successful image run. Signing uses `catalog-signing`. |
| `payload-after-images.yml` | With `AUTO_PAYLOADS`, publishes after successful main image builds. Installer-catalog adoption remains a separate step. |

Start with a publication dry run, then publish and deploy:

```sh
gh workflow run publish-cache.yml -R aurora-silicon/nixos-aurora --ref main -f dry-run=true
gh workflow run publish-cache.yml -R aurora-silicon/nixos-aurora --ref main -f deploy=yes
```

Optional `build-run`, `base-release` and `release-tag` inputs override automatic
selection. Explicit build IDs still undergo the normal admission checks. A dry
run publishes nothing; it uses a throwaway signing key for new outputs or
authenticates the existing cache when no new outputs are needed.

Deploy a chosen release or promote testing separately:

```sh
gh workflow run deploy-cache.yml -R aurora-silicon/nixos-aurora --ref main -f release-tag=cache-testing-YYYYMMDD.N
gh workflow run promote.yml -R aurora-silicon/nixos-aurora --ref main
```

See [development](development.md) for local checks and the
[shared update policy](https://github.com/aurora-silicon/aurora-distributions/blob/main/docs/updates.md)
for cross-distribution signing procedures. Artifact verification and physical
installation or hardware qualification remain separate results.
