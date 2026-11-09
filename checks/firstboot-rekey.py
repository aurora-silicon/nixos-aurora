"""Real PAM and LUKS software lifecycle; no initrd/Apple hardware qualification."""
import json
import shlex

machine.start()
machine.wait_for_unit("multi-user.target")
state = "/var/lib/aurora/firstboot"
boot = "/boot/omarchy"
device = "/var/lib/rekey-fixture.img"
partition = "11111111-2222-4333-8444-555555555555"
owner_password = "fixture-owner-password"
other_password = "fixture-existing-slot-password"
hook_env = "AURORA_UNIX_CHKPWD=/run/current-system/sw/bin/unix_chkpwd "


def authenticate(password, success=True):
    command = "printf '%s\\n' " + shlex.quote(password)
    command += " | " + hook_env + "pamtester aurora-fixture owner authenticate"
    return (machine.succeed if success else machine.fail)(command)


def unlock(password, success=True):
    command = "printf %s " + shlex.quote(password)
    command += " | cryptsetup open --test-passphrase --key-file=- " + device
    return (machine.succeed if success else machine.fail)(command)


def metadata():
    return json.loads(machine.succeed("cryptsetup luksDump --dump-json-metadata " + device))


machine.succeed(f"install -d -m 0700 {state} {boot} /etc/nixos /dev/disk/by-partuuid")
machine.succeed(f"truncate -s 64M {device}")
machine.succeed(f"printf fixture-temporary-key > {state}/luks-key")
machine.succeed(f"chmod 0600 {state}/luks-key; cp {state}/luks-key {boot}/luks-key")
# A test-only copy proves retirement invalidates the credential, not just its files.
machine.succeed(f"cp {state}/luks-key /root/original-fixture-key")
machine.succeed(f"cryptsetup luksFormat --batch-mode --type luks2 --pbkdf pbkdf2 --pbkdf-force-iterations 1000 --key-file {state}/luks-key {device}")
machine.succeed(f"ln -s {device} /dev/disk/by-partuuid/{partition}")
uuid = machine.succeed("cryptsetup luksUUID " + device).strip()
machine.succeed("printf %s " + shlex.quote(f"format=1\nphase=configured\npartition={partition}\nluks_uuid={uuid}\n") + f" > {boot}/encrypt.state")
machine.succeed(f"cryptsetup luksHeaderBackup {device} --header-backup-file {boot}/luks-header-before-recovery.bin")
machine.succeed(f"touch {state}/desktop")
machine.succeed("printf '%s\\n' '{ ... }: {}' > /etc/nixos/owner.nix")

with subtest("only a real owner password crosses the PAM handoff"):
    machine.fail("pamtester aurora-gate owner authenticate")
    machine.succeed("pamtester aurora-gate setup authenticate")
    authenticate("wrong-fixture-password", success=False)
    machine.fail("test -e /run/aurora-firstboot/password")
    assert set(metadata()["keyslots"]) == {"0"}

with subtest("an occupied owner slot is never replaced implicitly"):
    machine.succeed("printf %s " + shlex.quote(other_password) + f" | cryptsetup luksAddKey --batch-mode --pbkdf pbkdf2 --pbkdf-force-iterations 1000 --key-slot 1 --key-file {state}/luks-key {device} -")
    authenticate(owner_password)
    machine.wait_for_file("/run/aurora-firstboot/password")
    machine.succeed("test $(stat -c %a /run/aurora-firstboot) = 700")
    machine.succeed("test $(stat -c %a /run/aurora-firstboot/password) = 600")
    machine.succeed("touch /run/allow-rekey-fixture")
    machine.wait_until_succeeds("systemctl is-failed aurora-disk-rekey.service")
    machine.fail(f"test -e {state}/disk-rekeyed")
    machine.succeed(f"test -f {state}/luks-key && test -f {boot}/luks-key")
    machine.succeed(f"cryptsetup open --test-passphrase --key-file /root/original-fixture-key {device}")
    unlock(other_password)
    unlock(owner_password, success=False)
    machine.succeed("grep -Fx '{ ... }: {}' /etc/nixos/owner.nix")
    machine.fail("test -e /run/aurora-firstboot/password")
    # Reset only the disposable fixture's occupied slot, on its temporary key's authority.
    machine.succeed(f"cryptsetup luksKillSlot --batch-mode --key-file {state}/luks-key {device} 1")
    machine.succeed("systemctl reset-failed aurora-disk-rekey.service")

with subtest("verified owner password replaces and retires the temporary key"):
    authenticate(owner_password)
    machine.wait_for_file(state + "/disk-rekeyed")
    machine.wait_until_succeeds("test $(systemctl show -P Result aurora-disk-rekey.service) = success")
    unlock(owner_password)
    assert set(metadata()["keyslots"]) == {"1"}
    machine.fail(f"cryptsetup open --test-passphrase --key-file /root/original-fixture-key {device}")
    for path in [state + "/luks-key", boot + "/luks-key", boot + "/luks-header-before-recovery.bin", "/run/aurora-firstboot/password"]:
        machine.fail("test -e " + path)
    machine.succeed(f"grep -Fx phase=finished {boot}/encrypt.state")
    machine.succeed("grep -F 'aurora.firstboot.passwordHooks = false;' /etc/nixos/owner.nix")
    machine.succeed("pamtester aurora-gate owner authenticate")

with subtest("completed hooks are inert and repeated service starts are idempotent"):
    before = machine.succeed("sha256sum " + device)
    authenticate(owner_password)
    authenticate("wrong-fixture-password", success=False)
    machine.succeed("systemctl start aurora-disk-rekey.service")
    machine.fail("test -e /run/aurora-firstboot/password")
    assert machine.succeed("sha256sum " + device) == before

with subtest("rekey cleanup preserves a hand-edited machine configuration"):
    edited = '{ ... }: { networking.hostName = "fixture-custom"; }'
    machine.succeed("printf '%s\\n' " + shlex.quote(edited) + " > /etc/nixos/owner.nix")
    # Simulate a delayed pre-completion handoff arriving after a successful
    # rekey. The finished journal must prevent any new keyslot operation.
    machine.succeed("printf %s " + shlex.quote(owner_password) + " > /run/aurora-firstboot/password")
    machine.succeed("systemctl start aurora-disk-rekey.service")
    assert machine.succeed("cat /etc/nixos/owner.nix").strip() == edited
    assert machine.succeed("sha256sum " + device) == before
    machine.fail("test -e /run/aurora-firstboot/password")
