# Updates: from a source branch to installed Macs

The cross-distribution overview, threat model and key procedures are in
[aurora-distributions/docs/updates.md](https://github.com/aurora-silicon/aurora-distributions/blob/main/docs/updates.md).
This page is the NixOS runbook.

## Installed systems

`modules/aurora.nix` adds the Aurora cache as an extra substituter and trusts `keys/cache.pub`
(`aurora-nixos-1`); cache.nixos.org stays the default, and Nix requires a trusted signature for every
substituted path.

`scripts/build-image` writes `/etc/nixos/flake.nix` and locks it. Its `aurora` input follows the Git
ref `channel-testing` (the `images.yml` default) or `channel-stable`, and `flake.lock` pins the exact
commit the image was built from (`scripts/follow-channel.py` rewrites only the lock's `original`). The
first rebuild therefore reproduces the installed system, and

```sh
sudo aurora-update   # nix flake update aurora --flake /etc/nixos && nixos-rebuild switch --flake /etc/nixos#aurora
```

takes the newest commit of the channel. A channel ref moves only after the signed cache that holds that
commit's outputs is live (`deploy-cache.yml` for testing, `promote.yml` for stable), so an update
substitutes the hardware packages instead of building them. `channel=pinned` keeps the exact-commit input.
Nothing updates unattended: `system.autoUpgrade` stays off, as on ALARM and Fedora, where updates are a
deliberate `pacman -Syu` or `dnf upgrade`. `/etc/nixos/README` on each installed Mac says the same.

### Stage 2 on rebuild

`nixosModules.installed` (`modules/installed.nix`) refreshes the ESP Stage 2 on every bootloader install
(`nixos-rebuild switch` or `boot`), exactly as `update-m1n1` does on ALARM and Fedora: aura, every Apple
device tree of the system's kernel and U-Boot in one `m1n1/boot.bin`, the same layout on every Mac
including the MacBook Neo.

- At build time `scripts/check-stage2.py` requires the file to start with the system's aura build, carry
  only device trees, one gzip U-Boot member and m1n1 option lines, and include the device trees of
  `aurora.stage2.requiredBoards` (`j700` by default). The build fails otherwise, so a rebuild stops before
  it switches.
- At install time `aurora-install-stage2` (`scripts/install-stage2.sh`) checks the input against its
  recorded digest and that the ESP is the mounted FAT partition this Mac booted from
  (`/proc/device-tree/chosen/asahi,efi-system-partition` when present) with an `m1n1` directory. An
  unchanged file is left alone. A changed one is written to `boot.bin.new`, verified, the previous file is
  kept as `m1n1/boot.bin.old` and the new one renamed into place. Any refusal leaves the ESP unchanged and
  fails the bootloader install loudly.
- Stage 1 (`aurora/stage1.bin` and the boot object) is never written; it belongs to the installer.
- The Apple Silicon module's own copy (`boot.loader.grub.extraFiles`, an unchecked overwrite with no
  backup) is removed on installed systems. `aurora.stage2.enable = false` stops Stage 2 updates entirely.

Recovery: boot the previous NixOS generation from GRUB if the new kernel misbehaves; if Stage 2 itself
does not boot, restore `m1n1/boot.bin.old` over `m1n1/boot.bin` from macOS or the recovery environment.

`tests/test_stage2.py` runs the real installer script against a temporary ESP (only the mount and partition
queries are stubbed) and covers update with backup, no-op, refusal on every failed check, Stage 1 left
untouched, and the channel lock rewrite. `checks.stage2-tools` (CI) shellchecks the installed commands;
`images.yml` builds `checks.stage2`, the checked Stage 2 itself, next to every image.

### Moving an existing install to the channel (one-time)

Images before Alpha 9 pin `/etc/nixos/flake.nix` to one commit. To follow testing:

```sh
sudo sed -i 's|github:aurora-silicon/nixos-aurora/[0-9a-f]\{40\}|github:aurora-silicon/nixos-aurora/channel-testing|' /etc/nixos/flake.nix
sudo nix flake update aurora --flake /etc/nixos
sudo nixos-rebuild switch --flake /etc/nixos#aurora
```

The first switch installs `aurora-update` and refreshes Stage 2 (keeping `m1n1/boot.bin.old`); later
updates are `sudo aurora-update`.

## Channels

One cache serves every channel: it is content-addressed and cumulative. `channel-testing` moves when a
cache release is deployed; `channel-stable` moves when `promote.yml` (a `stable-promotion` reviewer)
promotes a commit testing served, after checking that every hardware output of that commit is signed in
the live cache. `channels.json` on the `channels` branch records the live cache and both commits.

## Workflows

| Workflow | Trigger | Does |
|---|---|---|
| `track-sources.yml` | every 30 min (`TRACK_SOURCES`), manual | Moves `aura`, `kernel-aurora`, `mesa-aurora` to their branch tips: `sources.json` (`sha256` and `nix_hash`), `kernel/provenance.json`, `locks/aura.Cargo.lock`, the kernel or Mesa version in `overlay.nix`/`mesa.nix`; dispatches `checks.yml`; merges when green (`AUTO_MERGE_SOURCES`); mirrors archives |
| `checks.yml` | push, PR, manual | Builds; places pinned archives in the store first (`prefetch-sources.py`); exports an **unsigned** cache and attests the artifact |
| `publish-cache.yml` | after a main build and every 6 h (`AUTO_PUBLISH_TESTING`), manual | Finds the base snapshot and the eligible builds itself; collects and checks every NAR; signs only narinfo files in `testing-signing`; Nix verifies every signature and NAR; releases `cache-testing-YYYYMMDD.N` with an attestation; deploys with `AUTO_DEPLOY_TESTING` or `deploy=yes` |
| `deploy-cache.yml` | manual or called | Verifies every entry and NAR over HTTP, the attestation and that no pin moves backwards; deploys Pages; moves `channel-testing` |
| `promote.yml` | manual | Moves `channel-stable` after approval, soak time and cache coverage checks |
| `images.yml` | manual or after a testing deploy (`AUTO_IMAGES`, only when main is the deployed commit) | Builds an image and the checked Stage 2; `channel` (default `testing`) sets what `/etc/nixos/flake.nix` follows |
| `payload-after-images.yml` | after an image build (`AUTO_PAYLOADS`) | Signed payload release; catalog adoption stays manual |

## Common tasks

```sh
gh workflow run publish-cache.yml -R aurora-silicon/nixos-aurora --ref main -f dry-run=true
gh workflow run publish-cache.yml -R aurora-silicon/nixos-aurora --ref main -f deploy=yes
gh workflow run deploy-cache.yml -R aurora-silicon/nixos-aurora --ref main -f release-tag=cache-testing-YYYYMMDD.N
gh workflow run promote.yml -R aurora-silicon/nixos-aurora --ref main
```

## Notes

- The build job no longer holds the cache key. `scripts/sign-cache-metadata.py` signs Nix's path
  fingerprint (`1;path;narHash;narSize;references`) with OpenSSL; its test pins the format to a signature
  the production key made.
- Failed build attempts upload `failed-nix-<package>-attempt-N`, never `nix-<package>-closure`; the
  collector takes the newest artifact of each name and skips one without a build record.
