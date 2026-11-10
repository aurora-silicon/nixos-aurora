# Aurora SEP integration

The shared kernel builds SEP as a module. The root filesystem supplies the
identity state, boot-container device link and per-device calibration, so an
early built-in probe cannot initialize the driver reliably.

The boot timer starts the loader after local filesystems are available, without
holding up the desktop. fprintd also joins initialization when requested. The
modprobe alias blacklist only defers automatic probing: the service explicitly
loads SEP on every supported boot. The loader skips an older running
kernel with SEP built in, and starts normally after reboot into the module-based
kernel. The kernel comes from this flake, so there is no package requirement on it;
the units run only where `apple_sep` is a loadable module.

## Touch ID calibration: aurora-touchid-setup

The sensor's driver loads per-device factory data that no package can ship:
the calibration and, on sensors with a nonce session (MacBook Neo, M4 Pro),
the sensor's signed root key. The fingerprint node's `firmware-name` list in
the device tree names both, in that order; the driver falls back to
`apple/mesa_calibration.bin` and `apple/msrk-j700.bin`.

`aurora-touchid-setup` builds these files from this Mac's own data, read-only:

- Where the factory cache holds an FSC2 calibration (J700, J713, J616s), each
  file is rebuilt from the factory records on the Hardware volume of the iBoot
  System Container, sealed for this Mac. The seal must name the running Mac's
  chip, ECID and serial number and cover the record. This needs no macOS.
- Elsewhere (M1, M2) the container holds a comb record, which is installed as
  carved.

No calibration data is distributed or reused across machines. The enclave
alone verifies the signatures; the tool checks provenance and structure.

It runs in three cases, and never as routine boot work:

1. **A file is missing.** `aurora-touchid-setup.service` runs once at boot,
   before Touch ID starts. Its condition only checks that the files it
   installed or checked before still exist, so a boot with Touch ID in place
   skips it. It also runs on the first boot after installation, to record
   what is there.
2. **The enclave refused an installed file.** When the sensor does not
   attach, `aurora-sep-ready` looks in this boot's kernel log for a refused
   `LOAD_CALIBRATION` or `SENSOR_ROOT_KEY`, or a missing file. It then starts
   the service, which replaces the file. The driver loads it again at its own
   retry about 10 s later, or at the next enrolment or verify. There is at
   most one automatic rebuild per boot, and a second refusal is only logged.
3. **The owner runs it.** `sudo aurora-touchid-setup --check` reports what it
   would do and writes nothing. `sudo aurora-touchid-setup` sets up what is
   missing. `sudo aurora-touchid-setup --force-rebuild` rebuilds and replaces
   what differs. Add `--json` for a machine-readable result.

A file the tool did not install is never replaced, unless the enclave refused
it this boot or `--force-rebuild` asks for it. Every replacement keeps the old
bytes in `/var/lib/aurora-sep/rollback`. The new file is written atomically
with mode 0600 and read back. On NixOS the kernel's firmware path is on
`/run`, so the files are kept in `/var/lib/aurora-sep/firmware`, and the tool
and `aurora-sep.service` link them into that path (links only, nothing is
rebuilt). The last result is in
`/var/lib/aurora-sep/touchid-setup.json`, with one JSON line per run in
`touchid-setup.log`. Models without a fingerprint reader record that once and
are not checked again; SEP trusted keys start either way. After the files are
in place, enrol with `fprintd-enroll -f right-index-finger USER` (the last word
is the user name) or the desktop's fingerprint settings.

The SEP holds three fingerprints. When it is full, or the host store is, the
enrolment ends with `enroll-data-full` (GNOME Settings: "Fingerprint device
storage is full"; `fprintd-enroll` also says to remove a fingerprint first).
No fingerprint is deleted to make room, including one enrolled by another OS
on this Mac: remove one yourself with `fprintd-delete USER -f FINGER` or the
settings.

The factory-record reader and the sealed-record rebuild are Erik Bourget's
work. Read XART-SAFETY.md for persistent identity ownership constraints and
OS-IDENTITY.md for running Linux beside macOS.

## Readiness

On a Mac with a reader, `aurora-sep-ready.service` opens `/dev/sep-bio` before
fprintd starts, which restores the enrolled fingerprints. It reports Touch ID
ready only when the driver says the sensor attached, the fingerprints were
restored and a match can save its state past the xART guard. When matching is
blocked it logs the reason and the documented `xart_guard=0` opt-out and fails
the unit; when that cannot be told yet it logs "matching UNVERIFIED".

The Aurora libfprint build keeps the full upstream driver set and adds the SEP
biometric interface. Module reload cannot repeat the secure enclave handoff;
driver updates take effect after a full reboot.

## Starting Touch ID over: aurora-xart

`aurora-xart status` shows what the SEP driver reports and explains a stuck
keybag in plain words; `aurora-xart list` shows Linux's xART records and state
files. When the keybag is stuck or no longer loads, for example on an M1 Mac
whose Touch ID setup began on a kernel that guarded it and never finished
("identity keybag state is ambiguous: EEXIST" at every boot), start Touch ID
over:

    sudo aurora-xart reset-touchid

It refuses on a read-only install, when the driver is not running and when the
keybag works, asks you to type RESET, and moves the Touch ID state and every
user's prints for the Apple sensor into
`/var/lib/aurora-sep-touchid-reset-<time>/`. It keeps the xART guard's files
and the calibration. Reboot, then enrol every finger again; kernel trusted keys
sealed before the reset can no longer be unsealed.

## Where Touch ID is used

Enrol a finger in GNOME Settings > Users or in KDE System Settings > Users
(or with `fprintd-enroll`). Touch ID is then offered here:

| Where | Accepts |
|---|---|
| Lock screen | a fingerprint or the password |
| `sudo`, polkit authentication dialogs | a fingerprint or the password |
| Login screen (GDM, Plasma Login) | the password |
| Text console login, `su`, ssh | the password |

With `services.fprintd.enable`, nixpkgs defaults every PAM service's
`fprintAuth` to on, which also puts the fingerprint in front of the console
login, `su` and Plasma Login (through `login`). `modules/sep.nix` turns that
default off and sets `security.pam.services.<name>.fprintAuth` explicitly:
on for `sudo` and `polkit-1`, off for `login`, `su` and `sshd`.
`fprintAuth` adds `pam_fprintd` as `sufficient`, ahead of the password. The
lock screens use `gdm-fingerprint` and `kde-fingerprint` as GDM's and
Plasma's modules define them. Set `fprintAuth` on a service to change it.

The login screen asks for the password because a session started with a
fingerprint cannot unlock the keyring or KWallet; GNOME can offer fingerprint
there as well with `aurora.sep.greeterFingerprint.enable = true;`.

## Power button

The Touch ID sensor is the power button. A short press suspends and a 5 s
press powers off (`services.logind.settings.Login.HandlePowerKey` and
`HandlePowerKeyLongPress`, set with `lib.mkDefault`) at the console, on the
login screens and on minimal installs. GNOME sessions handle the button
themselves (power-button-action, suspend by default). In Plasma sessions
PowerDevil handles it, and `/etc/xdg/powerdevilrc` makes a short press
suspend; holding the button for a second opens the logout screen. Plasma
users change it in System Settings > Power Management.

## SELinux

NixOS does not support SELinux, so there is no policy module. The Fedora
package's `aurora-sep-selinux` labels `/dev/sep-bio` and lets fprintd read the
lid switch; here fprintd's `DeviceAllow` entries for `/dev/sep-bio` and
`char-input` are the access control there is.

## Kernel interface compatibility

The sensor gate accepts SEP interface v4 and v5 with a physical reader;
unknown interface versions and absent readers remain disabled. Both versions
use the same readiness diagnostics. libfprint uses the legacy enrolment request
on v4, and the account-bound request and persistence checks on v5. A failed
v5 enrolment never retries the v4 request. Install the companion patched
fprintd to retain host records when deleting from the device fails.
Keep the existing SEP OS identity and persistent state across this update.

See the [controller-approved v4/v5 qualification plan](https://github.com/aurora-silicon/aurora-sep-userspace/blob/2799b51243708d0a551b67d902472319f132c417/docs/sep-v5-test-plan.md) before removing the kernel hold.
