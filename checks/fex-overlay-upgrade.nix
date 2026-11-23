# Exercise the actual module and switch-to-configuration with small immutable
# stand-in layers; the guest Mesa build independently validates the real ELFs.
{ pkgs }:
let
  commit = pkgs.mesa.auroraCommit;
  # An x86-64 Vulkan driver beside the guest's loader (an ELF header up to
  # e_machine 62, then the layer's name), as the real layer has.
  layer = name: (pkgs.runCommand "fex-layer-${name}" { passthru = { inherit commit; }; } ''
    mkdir -p $out/usr/lib64
    echo ${name} > $out/usr/aurora-layer
    printf '\177ELF\002\001\001\000\000\000\000\000\000\000\000\000\003\000\076\000\n${name}\n' > $out/usr/lib64/libvulkan_aurora.so
    echo ${commit} > $out/.aurora-mesa-commit
  '');
  old = layer "old";
  new = layer "new";
  rootfs = "/var/lib/aurora/fex/guest root%Z";
in pkgs.testers.runNixOSTest {
  name = "aurora-fex-overlay-upgrade";
  # GitHub's arm64 runners have no /dev/kvm; QEMU falls back to TCG.
  requiredFeatures.kvm = false;
  nodes.machine = { lib, ... }: {
    imports = [ ../modules/fex-mesa.nix ];
    aurora.fexMesa.package = old;
    aurora.fexMesa.rootfs = rootfs;
    systemd.tmpfiles.rules = let path = p: builtins.toJSON (lib.replaceStrings [ "%" ] [ "%%" ] "${rootfs}/${p}"); in [
      "d ${path "usr/lib64"} 0755 root root -"
      "f ${path "usr/lib64/ld-linux-x86-64.so.2"} 0644 root root - stock"
    ];
    specialisation.new-layer.configuration.aurora.fexMesa.package = lib.mkForce new;
    specialisation.disabled.configuration.aurora.fexMesa.enable = false;
  };
  testScript = ''
    import json

    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.wait_for_unit("aurora-fex-mesa.service")
    rootfs = ${builtins.toJSON rootfs}
    unit = "/org/freedesktop/systemd1/unit/aurora_2dfex_2dmesa_2eservice"
    properties = "org.freedesktop.systemd1 " + unit + " org.freedesktop.systemd1.Unit "
    mounts = json.loads(machine.succeed("busctl --json=short get-property " + properties + "RequiresMountsFor"))
    assert rootfs in mounts["data"], mounts
    conditions = json.loads(machine.succeed("busctl --json=short get-property " + properties + "Conditions"))
    assert any(c[0] == "ConditionPathIsDirectory" and c[3] == rootfs + "/usr" for c in conditions["data"]), conditions
    provider = "/var/lib/aurora/fex/mesa-rootfs"
    bind = "/run/fex-emu/rootfs"
    config = "/run/fex-emu/Config.json"
    original = machine.succeed("readlink -f /run/current-system").strip()

    # FEX's global RootFS is the provider, through a read-only bind.
    def selected(name):
        assert json.loads(machine.succeed(f"cat {config}")) == {"Config": {"RootFS": bind}}
        machine.succeed(f"mountpoint -q {bind}")
        machine.succeed(f"test \"$(stat -c %d {bind})\" = \"$(stat -c %d {provider})\"")
        machine.fail(f"touch {bind}/should-be-read-only")
        machine.succeed(f"grep -x {name} {bind}/usr/aurora-layer")
        machine.succeed(f"grep -x stock {bind}/usr/lib64/ld-linux-x86-64.so.2")

    def unset():
        machine.fail(f"test -e {config}")
        machine.fail(f"mountpoint -q {bind}")

    def binds():
        return int(machine.succeed(f"findmnt -n -o TARGET --list | grep -cx {bind} || true").strip())

    machine.succeed(f"grep -x old {provider}/usr/aurora-layer")
    machine.fail(f"touch {provider}/should-be-read-only")
    selected("old")
    # Sessions no longer get FEX_ROOTFS: a user's own FEX config overrides
    # the global RootFS, and FEX_ROOTFS overrides both.
    fresh = "env -u __NIXOS_SET_ENVIRONMENT_DONE "
    machine.succeed(fresh + "-u FEX_ROOTFS bash -lc 'test -z \"''${FEX_ROOTFS:-}\"'")
    machine.fail("test -e /etc/systemd/user-environment-generators/60-aurora-fex-rootfs")
    # A switch to a new layer while an x86 program runs from the RootFS.
    machine.succeed(f"systemd-run --unit=fex-busy -p WorkingDirectory={bind} sleep 600")
    switch = original + "/specialisation/new-layer/bin/switch-to-configuration test"
    machine.succeed(switch)
    machine.succeed(f"grep -x new {provider}/usr/aurora-layer")
    machine.fail(f"touch {provider}/should-be-read-only")
    selected("new")
    assert binds() == 2, binds()
    machine.succeed("systemctl stop fex-busy.service")
    machine.succeed(original + "/bin/switch-to-configuration test")
    machine.succeed(f"grep -x old {provider}/usr/aurora-layer")
    machine.succeed("systemctl is-active aurora-fex-mesa.service")
    selected("old")
    assert binds() == 1, binds()
    machine.succeed(original + "/specialisation/disabled/bin/switch-to-configuration test")
    machine.fail(f"mountpoint -q {provider}")
    unset()
    machine.succeed(original + "/bin/switch-to-configuration test")
    machine.succeed(f"grep -x old {provider}/usr/aurora-layer")
    selected("old")
    machine.succeed("systemctl stop aurora-fex-mesa.service")
    machine.fail(f"mountpoint -q {provider}")
    unset()
    # A guest root without its x86-64 loader is not used.
    machine.succeed("mv '" + rootfs + "/usr/lib64/ld-linux-x86-64.so.2' /tmp/ld-linux")
    machine.succeed("systemctl start aurora-fex-mesa.service")
    machine.succeed(f"mountpoint -q {provider}")
    unset()
    machine.succeed("systemctl stop aurora-fex-mesa.service")
    machine.succeed("mv /tmp/ld-linux '" + rootfs + "/usr/lib64/ld-linux-x86-64.so.2'")
    machine.succeed("mv '" + rootfs + "/usr' '" + rootfs + "/saved-usr'")
    machine.succeed("systemctl start aurora-fex-mesa.service")
    machine.fail("systemctl is-active aurora-fex-mesa.service")
    machine.fail(f"mountpoint -q {provider}")
    machine.succeed("test \"$(systemctl show -P ConditionResult aurora-fex-mesa.service)\" = no")
    unset()
    machine.succeed("mv '" + rootfs + "/saved-usr' '" + rootfs + "/usr'")
    machine.succeed("systemctl start aurora-fex-mesa.service")
    machine.succeed(f"grep -x old {provider}/usr/aurora-layer")
    selected("old")
    # A full /run: no runtime config at all (FEX refuses an empty or partial
    # one, even with a user's own RootFS), and a journal line saying why.
    machine.succeed("systemctl stop aurora-fex-mesa.service")
    machine.succeed("mount -t tmpfs -o size=4k fex-full /run/fex-emu")
    machine.succeed("dd if=/dev/zero of=/run/fex-emu/fill bs=1k count=64 || true")
    machine.succeed("systemctl start aurora-fex-mesa.service")
    machine.succeed("systemctl is-active aurora-fex-mesa.service")
    machine.fail(f"test -e {config}")
    machine.succeed("test -z \"$(find /run/fex-emu -name '.Config.json.*')\"")
    machine.succeed("journalctl -b -u aurora-fex-mesa.service | grep -F \"can't write\"")
    machine.succeed("systemctl stop aurora-fex-mesa.service")
    machine.succeed("umount /run/fex-emu")
    machine.succeed("systemctl start aurora-fex-mesa.service")
    selected("old")
  '';
}
