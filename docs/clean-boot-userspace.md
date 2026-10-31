# Userspace boot defaults

BlueZ 5.86 can reach `mgmt_send_tlv()` with an empty parameter list even
with an unmodified main.conf. BlueZ 5.87 contains the upstream fix that
returns before the empty transaction; real configuration errors still log.
See [BlueZ #1972](https://github.com/bluez/bluez/pull/1972) and the
[5.87 release](https://github.com/bluez/bluez/releases/tag/5.87).
Aurora requires at least 5.87 (an evaluation assertion on NixOS, a package
dependency on Fedora and ALARM). No controller parameters are invented.

The optional Docker engine queries firewalld's **permanent** policy names
before adding `docker-forwarding`. Runtime policies are insufficient: a
permanent policy can be inactive while its zones are absent. Existing policy
settings remain untouched. A missing policy is created with the same ANY to
docker ACCEPT forwarding settings as before. Query and creation failures
remain failures; the old-firewalld UnknownMethod compatibility and concurrent
creator NAME_CONFLICT handling remain. No firewall rules or logging levels
are weakened. See [the upstream report](https://github.com/moby/moby/issues/53752).
The patch includes mocked D-Bus tests for each branch. Docker remains optional.

The optional `/var/swap/swapfile2` unit is ordered after
`/var/swap/swapfile`. Btrfs serializes swapfile activation as an exclusive
filesystem operation, so parallel activation can return EBUSY. Fedora and
ALARM install a vendor systemd drop-in; NixOS generates a drop-in. The files
are not created or resized, and this ordering does not pull in either swap
unit. Other swap paths retain their existing configuration.

ABRT's producers publish reports by renaming a `.new` staging directory.
An interrupted producer can leave it without the `time` file required by
libreport's `dd_opendir()`. The Fedora ABRT patch keeps startup report scanning
from locking or marking unpublished transactions. It preserves their bytes
and reports their location at notice level for recovery. Published incomplete
reports retain ABRT's not-reportable handling, and malformed published
reports still produce diagnostics. No crash spool data is deleted, renamed,
packaged or uploaded. ALARM and the pinned NixOS package set do not ship ABRT;
no substitute crash handler is installed there.

## Package scope and retirement

On Fedora, the ABRT recipe retains Fedora f44's spec from commit
`e274177613176e81562cd297e00e19eacd68e11b` with the staging patch and regression
check. The optional `docker-ce` recipe builds Moby 29.9.2 from a hash-verified
source archive and retains Docker's services, SELinux policies and separate
CLI/containerd dependencies. It uses Fedora's packaged tini-static instead of
fetching a binary during the build. It updates Docker CE installations; it
conflicts with `moby-engine`. Switching an existing Moby installation is an
explicit package-manager choice. No Docker engine is pulled in by the platform.

On ALARM, the optional docker recipe derives from Arch's 29.9.2 recipe
(commit `73f823426870d8b4b6a98016b4e296f695583737`),
retains its source checksums and adds the engine patch and regression check.
On NixOS the existing pinned Docker 29 derivation builds the patched engine;
the CLI, wrappers and exposed `.moby` output all use that derivation.

Remove the engine patch when the selected upstream release checks permanent
policy names before creation. Remove the ABRT patch when its startup scanner
respects the `.new` publication boundary. Keep the BlueZ minimum while 5.86
could otherwise resolve, and keep swap ordering while two conventional
swapfiles can coexist. Reverting these commits restores the prior recipes;
no target-side rollback is needed until packages are installed.

## Validation

Source checks are `python3 -m unittest discover -s tests`. Fedora also runs
`python3 images/test_configure.py`. Engine package checks execute
`TestSetupDockerForwardingPolicy` without a running Docker or firewalld daemon.
The ABRT package check compiles the actual startup scanner with report-I/O
stubs, exercises active and interrupted staging directories, publication,
complete and incomplete reports, and malformed published directories, and
checks that staging data and modes survive.

Hardware acceptance after a separately authorized package installation is
`journalctl -b -p 3 -o short-monotonic` on the next boot. Read-only captures do
not prove behavior after installing these candidates. Keep raw device
journals and crash records out of public pull requests.
