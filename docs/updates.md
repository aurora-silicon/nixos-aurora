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

`nixosModules.installed` (`modules/installed.nix`) refreshes the ESP Stage 2 on every bootloader install
(`nixos-rebuild switch` or `boot`), exactly as `update-m1n1` does on ALARM and Fedora: aura, every Apple
device tree of the system's kernel and U-Boot in one `m1n1/boot.bin`, the same layout on every Mac
including the MacBook Neo.

- At build time `scripts/check-stage2.py` requires the file to start with the system's aura build, carry
  only device trees, one gzip U-Boot member and m1n1 option lines, and include the device trees of
  `aurora.stage2.requiredBoards` (`j700`, `j616s` and `j614s` by default). The build fails otherwise, so a rebuild stops before
  it switches.
- At install time `aurora-install-stage2` (`scripts/install-stage2.sh`) checks the input against its
  recorded digest and that the ESP is the mounted FAT partition this Mac booted from
  (`/proc/device-tree/chosen/asahi,efi-system-partition` when present) with an `m1n1` directory, then
  hands the write to `aurora-stage2 install` (below). An unchanged file is left alone. Any refusal
  leaves the ESP unchanged and fails the bootloader install loudly.
- The aura build carries `share/aura/monitor-free` once its pinned source has no monitor. `overlay.nix`
  declares that in `auraMonitorFree`, and the aura build refuses a source that disagrees (`src/ctxr_exec.c`,
  or no `src/monitor.c`). aura 1.0.0b7 is the first pin without the monitor (aura#77), so `auraMonitorFree`
  is true.
- Such an aura moves the kernel into the CTXR window, which only a kernel built with
  `CONFIG_ARM64_CTXR_EXECMEM` keeps its code inside. Evaluation refuses `auraMonitorFree` without
  `kernelCtxrExecmem`, and the kernel build checks that flag against its resolved configuration, so it can
  be set only with a kernel pin that has aurora-silicon/linux#985. Every kernel pin since 4731456 has it, and
  `kernel/config` turns it on, so `kernelCtxrExecmem` is true.
- With the marker, a Mac that boots a Mach-O Stage 1 (`/proc/device-tree/compatible` names one of the chips
  in the installer's `AuraStage1Format.usesMachO`: T8130 and later, T6040 and later) gets
  `m1n1/boot-ctxr.bin`, from the build's `ctxr/boot-ctxr-<board>.bin`, with only this board's device trees.
  `m1n1/boot.bin` is never touched, because the padded Stage 1 these Macs enroll chainloads `boot-ctxr.bin`.
  M1 to M3 Macs only ever use `boot.bin`.
- A problem with one board's file never stops a rebuild. `scripts/build-ctxr-stage2.sh` warns and leaves the
  file out, and a Mach-O Mac whose board has no file gets a warning and an unchanged ESP.
- An image build has no device tree to read, because its Stage 2 comes from the Apple Silicon module's
  `extraFiles`. If its aura has the marker, `scripts/prepare-ctxr-stage2.py` adds `boot-ctxr.bin`, a copy of
  `boot.bin`, to the image's ESP, and `boot-ctxr-<board>.bin`, a copy of `boot-<board>.bin`, for each Mach-O
  board. The installer picks the board's file over the combined one. The script fails the image if any of
  them is over 16 MiB. Without the marker the image has no `boot-ctxr.bin`, and the installer refuses it on
  Mach-O Macs, so no Mac gets a `boot-ctxr.bin` that rebuilds don't refresh.
- Stage 1 (`aurora/stage1.bin`, `aurora/stage1.macho` and the boot object) is never written; it belongs
  to the installer.
- The Apple Silicon module's own copy (`boot.loader.grub.extraFiles`, an unchecked overwrite with no
  backup) is removed on installed systems. `aurora.stage2.enable = false` stops Stage 2 updates, the trial
  units and the pre-switch check entirely.

### Device trees and the next boot

The device trees in Stage 2 are shared by every configuration GRUB lists, so a new set is tried before it
replaces the working one. This is fedora-aurora's updater
([fedora-aurora#193](https://github.com/aurora-silicon/fedora-aurora/pull/193), its `docs/updates.md`):
`stage2/bootchain.py` and its test suite are copied unchanged (`stage2/provenance.json` records the source
commit and digests, and a test fails if the copies drift), and `stage2/nixos_stage2.py` adapts it to NixOS
generations. `pkgs.aurora-stage2` packages both.

With aura Stage 1 1.0.0b4 or later (read from `/proc/device-tree/chosen`, not from the aura package),
`aurora-stage2 install` leaves the working file in place. It writes `m1n1/<name>.next`, reads it back,
checks its DTB headers, that a tree for this Mac's root compatible is there and that it keeps the display
aliases (`dcp`, `disp0`) the running tree has, records a receipt (`<name>.next.json`) and an attempt under
`/var/lib/aurora-stage2/attempts`, flushes the ESP, and only then writes the ESP root file `aura-try` as
`armed\n<ESP-relative .next path>\n` through `aura-try.tmp`. Stage 1 marks it `spent` before it loads the
candidate, so any failure boots the configured file next time. Older Stage 1 gets the file directly: it is
written beside the target, verified, the previous file kept as `m1n1/<name>.old` and the new one renamed
into place.

On the trial boot `aurora-stage2-commit.service` runs once, after `multi-user.target`, when the ESP has an
`aura-try` marker. It commits only when `/proc/device-tree/chosen/aurora,trial` names the candidate, the
candidate still matches its receipt, root is on NVMe, no device-tree device is left in deferred probe
(debugfs `devices_deferred`) and every enabled DCP has a bound driver. It then saves `<name>.prev`, renames
`.next` over the live file, flushes the ESP, checks the live file's SHA-256 and removes the marker; a failed
write or read-back puts the previous file back and keeps the candidate. `aurora-stage2-guard.timer` reboots
a trial boot that has not committed after twelve minutes (a Linux that feeds the watchdog but cannot pass
the checks), which boots the configured file. After a fallback the commit service logs that once per boot
and leaves `.next` and `.next.json` for inspection. `journalctl -u aurora-stage2-commit -u
aurora-stage2-guard` shows what happened.

NixOS generations and rollback:

- The trial is decided by the bootloader install of the configuration that becomes GRUB's default
  (`nixos-rebuild switch` or `boot`, and `switch --rollback`). Its Stage 2 is the one built with that
  configuration's kernel. `nixos-rebuild test` installs no bootloader and changes nothing on the ESP.
- One attempt per candidate image (its SHA-256, recorded in the receipt's `kernel` field), not per kernel
  version: an image that fell back is never armed again automatically, and any other image (new device
  trees, aura, U-Boot or m1n1 options) gets its own trial, keeping the failed one as
  `<name>.failed-<sha256>`.
- The newest install decides: an armed candidate that never booted is withdrawn, with its attempt record,
  when a later install selects other bytes, so `nixos-rebuild boot` twice before a reboot trials the second
  image, and going back to a configuration whose Stage 2 is the live file disarms the newer candidate.
- A trial boot that has not committed refuses a new install (wait for the commit, or reboot). Once it has
  committed, the next install may arm the next image.
- Booting another generation from GRUB does not change Stage 2: every entry boots with the live device
  trees, which is what the DT ABI guard protects.
- A switch back to a configuration from before this change runs that configuration's own installer, which
  replaces the file directly and does not know about `aura-try`. Do that only without an armed trial.

### DT ABI generations

`kernel/dtb-abi` is the kernel's DT ABI generation, the integer fedora-aurora ships as
`packages/kernel-aurora/dtb-abi` (currently 1); `overlay.nix` exposes it as the kernel's `auroraDtbAbi`,
and `modules/aurora.nix` writes it into every generation as `aurora-dtb-abi`. Device trees change within a
generation; only a change older kernels cannot boot with raises it.

A changed Stage 2 is refused while a configuration GRUB lists (every profile's newest
`boot.loader.grub.configurationLimit` generations, named profiles under `system-profiles`, and their
specialisations) has a lower generation. A configuration without `aurora-dtb-abi`, built before this
change, has the generation of a listed configuration that boots the same kernel store path, or 0. The
refusal comes from `system.preSwitchChecks` before GRUB's menu changes, again at install time, and again
before a commit, and names the configurations and the `nix-env --delete-generations` command that removes
them. Nothing is removed automatically: keep a configuration you know boots. An unchanged Stage 2 is never
refused, as the listed configurations already boot with it.

So the first kernel update after this lands is refused while a listed configuration from before it has a
different kernel and a later DT ABI generation: those count as generation 1, as Fedora counts kernels
without the file.

### What differs from Fedora

The behaviour above is Fedora's, except: the Stage 2 is the one built and checked with the configuration
instead of one composed from `/boot`; the retained kernels are the configurations GRUB lists instead of
the installed kernel packages, with same-kernel inheritance for undeclared ones; the guard applies only when
the ESP file would change; an untried armed candidate is withdrawn by a later install instead of refusing
it; and there is no `/boot/dtb` link, because each NixOS generation boots its own kernel's trees through
Stage 2. As on Fedora since fedora-aurora#207, attempts are recorded per image (its SHA-256), so an aura,
U-Boot or option change gets its own trial on the same kernel; an image that fell back is never armed
again automatically, while one that committed may be after a rollback to it; and a trial boot that
committed stages the next image like an ordinary boot.

Recovery: boot the previous NixOS generation from GRUB if the new kernel misbehaves. If a committed Stage 2
does not boot, restore `m1n1/<name>.prev` (after a trial) or `m1n1/<name>.old` (after a direct update) over
`m1n1/<name>` from macOS or the recovery environment, and remove `aura-try`.

### Tests

`tests/test_stage2.py` runs the real installer script against a temporary ESP (only the mount and partition
queries are stubbed) and covers update with backup, no-op, refusal on every failed check, the hand-off to
the trial updater, DT ABI refusal over listed generations, Stage 1 left untouched, and the channel lock
rewrite. `stage2/test_nixos_stage2.py` covers the NixOS transactions: arming, the trial-boot commit, fallback
without re-arming, the guard reboot, the CTXR slot, DT ABI refusal (limits, specialisations, named profiles,
same-kernel inheritance, a configuration added after arming) and the newest-install rules;
`stage2/test_bootchain.py` is fedora-aurora's suite for the shared code. `tests/test_stage2_trial.py` runs
both with the repository tests when `dtc` is installed. `checks.stage2-trial` (CI) runs both suites against
the packaged copies and checks the units, the pre-switch check and the generation record by evaluation;
`checks.stage2-tools` shellchecks the installed commands; `images.yml` builds `checks.stage2`, the checked
Stage 2 itself, next to every image.

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
