# ANE userspace packaging

These opt-in packages install no kernel modules, device-tree overlays, DKMS,
boot hooks, Apple firmware, or Apple models. The Aurora kernel supplies the driver.

| Payload | Fedora | ALARM | NixOS |
| --- | --- | --- | --- |
| omarchy-ane-tools | 0.5.7-2 | 0.5.7-2 | 0.5.7 |
| mil-hwx-compiler (mil-hwxc) | 0.3.1-1 | 0.3.1-1 | 0.3.1 |
| Tool commands | omarchy-ane-run, omarchy-ane-smoke, omarchy-ane-firmware-fetch | same | same |
| Smoke fixtures | h13-anec/add/program-0.anec, h14-anec/add/program-0.anec | same | same |
| Permissions | accel group, 0660, 70-omarchy-ane.rules | same | same |
| Shared inference runtime | reserved for t-3650 release | same | same |

The compiler pin is upstream tag v0.3.1, commit
927013f5480768b07c8e62a866e1514c41aba778. The MIT compiler installs only
`bin/mil-hwxc` and its license. On Fedora and ALARM, the recipe also builds
private `libobjc2` and GNUstep Base libraries from the exact commits in upstream's
bootstrap script, using verified archives and no build-time downloads. These
MIT/LGPL-2.1-or-later libraries live under `lib/mil-hwx-compiler`, with their
licenses, and do not replace or provide the system's GNUstep ABI. NixOS uses
nixpkgs' libobjc2/make and a compiler-private Base 1.31.1 derivation from the
same source pin and upstream fix as runtime dependencies. No macOS frameworks
or compiled Apple model examples are installed. The compiler's H13 software
suite runs in every recipe; no device is needed.

The tools install the upstream MIT userspace runner (statically linked libane),
smoke and fetch scripts, the two add fixtures and LICENSE. A common small patch
makes smoke resolve fixtures relative to its installation prefix and names the
correct package in recovery messages. The rule and smoke patch are identical
across the three recipes. NixOS additionally patches interpreter/store paths
and the firmware location as described below. All three carry the same sysusers
entry; NixOS also declares the group through its module.

Enroll only intended users in `accel` (Fedora/ALARM: `sudo usermod -aG accel USER`;
NixOS: `users.users.USER.extraGroups = [ "accel" ];`), then log in again.
Reload udev rules and retrigger the accel device, or reboot, after installation.
Run `omarchy-ane-smoke`: it checks 20 add calls and emits one JSON result.
An unsupported chip or missing driver returns exit 2. Firmware fetching is
always an explicit owner action; no install hook runs it.

The shared inference runtime is deliberately not represented by a dummy package
or a hard dependency. Once t-3650 publishes an API and release, add its source
pin, CLI/library payload and optional integration in all three repositories.
This compiler package does not promise that every target is device-proven.

## NixOS firmware handoff

Enable `aurora.ane.enable = true;` in the Aurora NixOS module. This installs the
commands and rule and declares `accel`. Merely adding the package to
`environment.systemPackages` does not register its udev rule.

M1-family Macs use iBoot's preloaded firmware and need no fetched package.
On M2, `sudo omarchy-ane-firmware-fetch` stages the pin-checked raw image under
`/var/lib/aurora/ane-firmware/apple/ane`. It does not write `/usr`, the ESP, or
any macOS volume. Nothing fetches at evaluation, build, activation, or boot.
Then supply those local bytes to `hardware.firmware` through the module:

```nix
{ pkgs, ... }: {
  aurora.ane.enable = true;
  aurora.ane.firmwarePackage = pkgs.runCommand "local-ane-firmware" {
    src = builtins.path {
      path = /var/lib/aurora/ane-firmware;
      name = "local-ane-firmware-source";
    };
  } ''
    mkdir -p "$out/lib/firmware/apple/ane"
    cp "$src"/apple/ane/*.macho "$out/lib/firmware/apple/ane/"
  '';
}
```

Use `sudo nixos-rebuild switch --impure --flake ...` on this Mac when a flake
needs access to that absolute local path, then reboot to reprobe the driver.
This copies the owner's firmware into the local Nix store; keep the derivation,
its inputs and its closure out of public caches, images and source control.
The package may instead come from another owner-controlled local Nix expression;
its only required layout is `lib/firmware/apple/ane/<driver-requested-name>`.

The module marks only this firmware package as uncompressed, so the upstream
fetcher's raw-image hash check remains meaningful. NixOS joins it into the
system firmware tree exposed at `/run/current-system/firmware`; Aurora's
`/lib/firmware` fallback links there while `firmware_class.path` retains the
per-device ESP handoff at `/run/aurora-firmware/vendorfw`. Thus the kernel sees
the owner-supplied file without a new global search-path override. Other
firmware packages keep their normal compression policy.

`omarchy-ane-firmware-fetch --check` checks the active loader/vendor paths and
then the activated system firmware tree. A staged file alone fails the check;
an earlier conflicting vendor file is still refused. Fetch and rebuild after
updating a pin. An existing wrong-pin vendor image must be corrected by the
owner; the fetcher does not overwrite it. Smoke uses this same check for its
missing-driver diagnostic.

Rollback: remove `aurora.ane.firmwarePackage`, rebuild and reboot. Disable
`aurora.ane.enable` to remove tools and the rule. The explicitly fetched staging
files remain local until the owner deletes them; old Nix generations retain
local firmware until normal generation deletion and garbage collection.

Build `nix build .#omarchy-ane-tools .#mil-hwx-compiler` and run
`nix flake check --no-build` plus `nix build .#checks.aarch64-linux.ane-packaging`.
The latter uses a synthetic marker, never Apple firmware, to check that the
module's firmware package remains uncompressed and the rule is registered.

Fixture provenance: H13's upstream README identifies the open encoder output.
H14 add SHA-256 is
`b416b9d14059a0918f6b05bfcf4a8ba982dd92e7b25f2b042c1a15f1ab2a439a`.
The compiler v0.3.1's `tests/test_h14_fixture_programs.py` regenerates it from
`tests/fixtures/h14/add.mil` and checks this exact hash. All three compiler
recipes run that software suite, closing the earlier H14 provenance gap.


Source redistribution: the full upstream archives include unrelated binary
research inputs. `redistribute_source = false` excludes both archives from
Aurora's source mirror. Builders fetch and hash-check upstream directly;
only the explicit userspace output file lists are distributed. Fedora uses
NoSource: 0 and publishes `.nosrc.rpm` recipe packages (the GNUstep dependency
sources remain included). To rebuild one, first fetch the upstream source pin
with `scripts/fetch-sources.py PACKAGE --output SOURCES`. ALARM source exports
must use `makepkg --source`, which omits remote archives, rather than
`--allsource`. Nix publishes runtime outputs/closures, never these source
fetcher outputs. Owner-fetched firmware remains outside all distributable builds.


The private Fedora/ALARM GNUstep Base pin carries upstream fix
[4a61eee44f53](https://github.com/gnustep/libs-base/commit/4a61eee44f537e5f83f68d447c29a6e5b6e40fdc),
which removes an invalid `__block` instance-variable qualifier. NixOS uses the same Base pin/fix in a compiler-private derivation with
nixpkgs' libobjc2/make. Base 1.29 lacks required compiler APIs; the system
GNUstep package is not overridden.
