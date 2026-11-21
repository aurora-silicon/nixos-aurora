"""Synthetic SEP device boundary, actual systemd transactions/readiness logic."""
machine.start()
machine.wait_for_unit("multi-user.target")
base = "/run/sep-fixture"
diag = base + "/devices/fixture.sep/diag"
units = "fprintd.service aurora-sep-ready.service aurora-touchid-setup.service aurora-sep.service"
machine.succeed(f"mkdir -p {diag} /run/aurora-sep /dev/disk/by-partlabel")
machine.succeed(f"touch {base}/events {base}/calibration")
machine.succeed(f"printf '%s\\n' {base}/calibration > {base}/touchid-files")
for attribute, value in {"touchid": "ready", "sensor_attach": "attached", "restore": "restored", "matching": "usable"}.items():
    machine.succeed(f"printf '%s\\n' {value} > {diag}/{attribute}")


def reset():
    machine.succeed("systemctl stop " + units)
    # Successful skipped/stopped units may already have been garbage-collected.
    machine.succeed("systemctl reset-failed")
    machine.succeed(f": > {base}/events")


def events():
    return machine.succeed("cat " + base + "/events").splitlines()


with subtest("the platform partition condition skips all device work"):
    machine.succeed("systemctl start aurora-sep.service")
    machine.fail("systemctl is-active aurora-sep.service")
    assert events() == [], events()

with subtest("a kernel without the loadable SEP module skips its loader"):
    machine.succeed("touch /dev/disk/by-partlabel/iBootSystemContainer")
    machine.succeed(f"touch {base}/no-module")
    machine.succeed("systemctl start aurora-sep.service")
    machine.fail("systemctl is-active aurora-sep.service")
    assert "load" not in events(), events()
    machine.succeed(f"rm {base}/no-module")

with subtest("a device without a physical reader does not run readiness or fprintd"):
    reset()
    machine.succeed(f"touch {base}/no-reader")
    machine.succeed("systemctl start fprintd.service")
    machine.succeed("systemctl is-active aurora-sep.service")
    machine.fail("systemctl is-active fprintd.service")
    machine.fail("systemctl is-active aurora-sep-ready.service")
    assert events() == ["load"], events()
    machine.succeed(f"rm {base}/no-reader")

with subtest("loading and real readiness finish before the fingerprint daemon"):
    reset()
    machine.succeed("systemctl start fprintd.service")
    machine.wait_for_unit("fprintd.service")
    machine.succeed("systemctl is-active aurora-sep-ready.service")
    assert events() == ["load", "ready", "fprintd"], events()
    machine.fail("systemctl is-active aurora-touchid-setup.service")

with subtest("a refusal starts the actual repair unit once, then readiness can retry"):
    reset()
    machine.succeed(f"printf 'not-ready\\n' > {diag}/sensor_attach")
    machine.succeed(f"printf 'not-ready\\n' > {diag}/touchid")
    # The fixture supplies the diagnostic input; the real readiness helper
    # still starts the real systemd repair job and observes its marker.
    machine.succeed(f"touch {base}/refusal")
    machine.fail("systemctl start aurora-sep-ready.service")
    machine.wait_until_succeeds(f"test -f /run/aurora-sep/touchid-auto-rebuild && grep -qx setup {base}/events")
    machine.wait_until_succeeds("test $(systemctl show -P ActiveState aurora-touchid-setup.service) = inactive")
    assert events().count("setup") == 1, events()
    assert events().index("load") < events().index("ready") < events().index("setup"), events()
    machine.succeed("systemctl reset-failed aurora-sep-ready.service")
    machine.succeed("systemctl start aurora-sep-ready.service")
    machine.succeed("systemctl is-active aurora-sep-ready.service")

with subtest("a second refusal does not repeat automatic repair in this boot"):
    machine.succeed("systemctl stop aurora-sep-ready.service")
    machine.succeed(f"printf 'not-ready\\n' > {diag}/sensor_attach")
    machine.succeed(f"printf 'not-ready\\n' > {diag}/touchid")
    machine.fail("systemctl start aurora-sep-ready.service")
    assert events().count("setup") == 1, events()
    machine.succeed("journalctl -u aurora-sep-ready.service -b --no-pager | grep -F 'automatic rebuild already ran this boot'")

with subtest("blocked xART matching stays a readiness failure"):
    machine.succeed(f"printf 'attached\\n' > {diag}/sensor_attach")
    machine.succeed(f"printf 'ready\\n' > {diag}/touchid")
    machine.succeed(f"printf 'blocked\\n' > {diag}/matching")
    machine.succeed(f"printf 'disabled\\n' > {diag}/xart")
    machine.succeed("systemctl reset-failed aurora-sep-ready.service")
    machine.fail("systemctl start aurora-sep-ready.service")
    machine.succeed("journalctl -u aurora-sep-ready.service -b --no-pager | grep -F 'xART writes are disabled'")
    assert events().count("setup") == 1, events()

with subtest("a truncated host-state store is recovered before the loader"):
    # The unit and its helper come from the shared SEP userspace package;
    # modules/sep.nix only orders them before the loader. A file the driver
    # would refuse is moved to the quarantine, so Touch ID survives a power
    # cut instead of dying with the loader.
    machine.succeed("printf 'cut off by a power cut' > /var/lib/aurora-sep-host-state.bin")
    machine.succeed("systemctl start aurora-sep-host-state-repair.service")
    machine.wait_for_unit("aurora-sep-host-state-repair.service")
    machine.fail("test -e /var/lib/aurora-sep-host-state.bin")
    machine.succeed("test -f /var/lib/aurora-sep-quarantine/host-state-*.bin")
    machine.succeed(
        "journalctl -u aurora-sep-host-state-repair.service -b --no-pager"
        " | grep -F 'the driver will create a fresh store'"
    )
    # The shipped unit's Before= and the module's wantedBy make the loader
    # run the recovery first.
    machine.succeed("systemctl show aurora-sep.service --property=After | grep -q aurora-sep-host-state-repair.service")
    machine.succeed("systemctl show aurora-sep.service --property=Wants | grep -q aurora-sep-host-state-repair.service")
