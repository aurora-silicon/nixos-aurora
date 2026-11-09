# Exercise the actual module and switch-to-configuration with small immutable
# stand-in layers; the guest Mesa build independently validates the real ELFs.
{ pkgs }:
let
  commit = pkgs.mesa.auroraCommit;
  layer = name: (pkgs.runCommand "fex-layer-${name}" { passthru = { inherit commit; }; } ''
    mkdir -p $out/usr
    echo ${name} > $out/usr/aurora-layer
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
    systemd.tmpfiles.rules = [
      "d ${builtins.toJSON (lib.replaceStrings [ "%" ] [ "%%" ] "${rootfs}/usr")} 0755 root root -"
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
    generator = "/etc/systemd/user-environment-generators/60-aurora-fex-rootfs"
    original = machine.succeed("readlink -f /run/current-system").strip()
    machine.succeed(f"grep -x old {provider}/usr/aurora-layer")
    machine.fail(f"touch {provider}/should-be-read-only")
    # Exercise both environment entry points, not only the mount unit.
    machine.succeed(f"env -u FEX_ROOTFS {generator} | grep -Fx FEX_ROOTFS={provider}")
    machine.succeed(f"test -z \"$(FEX_ROOTFS=/explicit/guest {generator})\"")
    # The driver shell already initialized NixOS's global environment. Clear
    # its inherited guard as well, to model a fresh session rather than a
    # child shell whose parent deliberately removed just FEX_ROOTFS.
    fresh = "env -u __NIXOS_SET_ENVIRONMENT_DONE "
    machine.succeed(fresh + "-u FEX_ROOTFS bash -lc 'test \"$FEX_ROOTFS\" = " + provider + "'")
    machine.succeed(fresh + "FEX_ROOTFS=/explicit/guest bash -lc 'test \"$FEX_ROOTFS\" = /explicit/guest'")
    switch = original + "/specialisation/new-layer/bin/switch-to-configuration test"
    machine.succeed(switch)
    machine.succeed(f"grep -x new {provider}/usr/aurora-layer")
    machine.fail(f"touch {provider}/should-be-read-only")
    machine.succeed(original + "/bin/switch-to-configuration test")
    machine.succeed(f"grep -x old {provider}/usr/aurora-layer")
    machine.succeed("systemctl is-active aurora-fex-mesa.service")
    machine.succeed(original + "/specialisation/disabled/bin/switch-to-configuration test")
    machine.fail(f"mountpoint -q {provider}")
    machine.fail(f"test -e {generator}")
    machine.succeed(fresh + "-u FEX_ROOTFS bash -lc 'test -z \"''${FEX_ROOTFS:-}\"'")
    machine.succeed(fresh + "FEX_ROOTFS=/explicit/guest bash -lc 'test \"$FEX_ROOTFS\" = /explicit/guest'")
    machine.succeed(original + "/bin/switch-to-configuration test")
    machine.succeed(f"grep -x old {provider}/usr/aurora-layer")
    machine.succeed("systemctl stop aurora-fex-mesa.service")
    machine.fail(f"mountpoint -q {provider}")
    machine.succeed(f"test -z \"$(env -u FEX_ROOTFS {generator})\"")
    machine.succeed(fresh + "-u FEX_ROOTFS bash -lc 'test -z \"''${FEX_ROOTFS:-}\"'")
    machine.succeed("mv '" + rootfs + "/usr' '" + rootfs + "/saved-usr'")
    machine.succeed("systemctl start aurora-fex-mesa.service")
    machine.fail("systemctl is-active aurora-fex-mesa.service")
    machine.fail(f"mountpoint -q {provider}")
    machine.succeed("test \"$(systemctl show -P ConditionResult aurora-fex-mesa.service)\" = no")
    machine.succeed("mv '" + rootfs + "/saved-usr' '" + rootfs + "/usr'")
    machine.succeed("systemctl start aurora-fex-mesa.service")
    machine.succeed(f"grep -x old {provider}/usr/aurora-layer")
  '';
}
