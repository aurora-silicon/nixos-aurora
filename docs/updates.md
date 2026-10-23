# Updates: from a source branch to installed Macs

The cross-distribution overview, threat model and key procedures are in
[aurora-distributions/docs/updates.md](https://github.com/aurora-silicon/aurora-distributions/blob/main/docs/updates.md).
This page is the NixOS runbook.

## Installed systems

`modules/aurora.nix` adds the Aurora cache as an extra substituter and trusts `keys/cache.pub`
(`aurora-nixos-1`); cache.nixos.org stays the default, and Nix requires a trusted signature for every
substituted path.

`scripts/build-image` writes `/etc/nixos/flake.nix`. With the `images.yml` input `channel=pinned` (the
default, today's behaviour) its `aurora` input is the exact image commit and the system never updates
until the owner edits it. With `testing` or `stable` it follows the Git ref `channel-testing` or
`channel-stable`: `sudo nix flake update --flake /etc/nixos && sudo nixos-rebuild switch --flake
/etc/nixos#aurora` takes the newest commit whose outputs are in the signed cache.

`nixosModules.installed` disables the Apple Silicon boot module, so a rebuild installs a new kernel and
initrd but leaves the ESP Stage 2 (aura and its DTBs) as installed. Device firmware is read from the ESP
at boot.

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
| `images.yml` | manual or after a testing deploy (`AUTO_IMAGES`, only when main is the deployed commit) | Builds an image; `channel` sets what `/etc/nixos/flake.nix` follows |
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
