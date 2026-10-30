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
in pkgs.testers.runNixOSTest {
  name = "aurora-fex-overlay-upgrade";
  nodes.machine = { lib, ... }: {
    imports = [ ../modules/fex-mesa.nix ];
    aurora.fexMesa.package = old;
    systemd.tmpfiles.rules = [ "d /var/lib/aurora/fex/rootfs/usr 0755 root root -" ];
    specialisation.new-layer.configuration.aurora.fexMesa.package = lib.mkForce new;
  };
  testScript = ''
    machine.start()
    machine.wait_for_unit("aurora-fex-mesa.service")
    provider = "/var/lib/aurora/fex/mesa-rootfs"
    original = machine.succeed("readlink -f /run/current-system").strip()
    machine.succeed(f"grep -x old {provider}/usr/aurora-layer")
    machine.fail(f"touch {provider}/should-be-read-only")
    switch = original + "/specialisation/new-layer/bin/switch-to-configuration test"
    machine.succeed(switch)
    machine.succeed(f"grep -x new {provider}/usr/aurora-layer")
    machine.fail(f"touch {provider}/should-be-read-only")
    machine.succeed(original + "/bin/switch-to-configuration test")
    machine.succeed(f"grep -x old {provider}/usr/aurora-layer")
    machine.succeed("systemctl is-active aurora-fex-mesa.service")
    machine.succeed("systemctl stop aurora-fex-mesa.service")
    machine.fail(f"mountpoint -q {provider}")
  '';
}
