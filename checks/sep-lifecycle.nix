# Exercise systemd's real conditions/ordering and the packaged readiness and
# setup-needed helpers. Only device-facing load/sensor/extraction endpoints
# and refused-calibration log inputs are synthetic; no Apple device, APFS
# data or calibration is accessed.
{ pkgs }:
let
  journal = pkgs.writeShellScriptBin "journalctl" ''
    if [ -e /run/sep-fixture/refusal ]; then
      printf 'sensor: LOAD_CALIBRATION refused (Aurora test fixture)\n'
    fi
  '';
  fixture = pkgs.runCommand "aurora-sep-lifecycle-fixture" {} ''
    cp -r ${pkgs.aurora-sep}/. $out
    chmod -R u+w $out
    cp ${pkgs.writeShellScript "fixture-sep-load" ''
      echo load >> /run/sep-fixture/events
      ${pkgs.coreutils}/bin/ln -sf /dev/null /dev/sep-bio
    ''} $out/libexec/aurora-sep-load
    cp ${pkgs.writeShellScript "fixture-sensor-present" ''
      test ! -e /run/sep-fixture/no-reader
    ''} $out/libexec/aurora/sensor-present
    cp ${pkgs.writeShellScript "fixture-touchid-publish" "exit 0"} $out/libexec/aurora/touchid-publish
    # Userspace /dev/kmsg writes are filtered from journalctl -k. Supply
    # this one input explicitly while running the unchanged packaged body.
    cp ${pkgs.writeShellScript "fixture-sep-readiness" ''
      export PATH=${pkgs.lib.makeBinPath [ journal pkgs.bash pkgs.coreutils pkgs.gnugrep pkgs.systemd ]}:$PATH
      exec ${pkgs.aurora-sep}/libexec/.aurora-sep-ready-wrapped "$@"
    ''} $out/libexec/aurora-sep-ready
    cp ${pkgs.writeShellScript "fixture-touchid-setup" ''
      echo setup >> /run/sep-fixture/events
      ${pkgs.coreutils}/bin/touch /run/aurora-sep/touchid-auto-rebuild
      ${pkgs.coreutils}/bin/touch /run/sep-fixture/calibration
      # Simulate the driver accepting the repaired file on its next retry.
      printf 'attached\n' > /run/sep-fixture/devices/fixture.sep/diag/sensor_attach
      printf 'ready\n' > /run/sep-fixture/devices/fixture.sep/diag/touchid
    ''} $out/bin/aurora-touchid-setup
  '';
  modinfo = pkgs.writeShellScriptBin "modinfo" ''
    [ ! -e /run/sep-fixture/no-module ] || exit 1
    printf '/fixture/apple_sep.ko.zst\n'
  '';
  # Stands in for Aurora's fprintd, so it satisfies modules/sep.nix's guard.
  fprintd = pkgs.runCommand "fixture-fprintd" { passthru.auroraNoEnrollGc = 1; } ''
    mkdir -p $out/libexec
    cp ${pkgs.writeShellScript "fixture-fprintd" ''
      echo fprintd >> /run/sep-fixture/events
      exec ${pkgs.coreutils}/bin/sleep infinity
    ''} $out/libexec/fprintd
  '';
in pkgs.testers.runNixOSTest {
  name = "aurora-sep-lifecycle";
  requiredFeatures.kvm = false;
  node.pkgs = pkgs.lib.mkForce (pkgs.extend (_: prev: {
    aurora-sep = fixture;
    # The test never runs libfprint; don't build the hardware implementation.
    libfprint = prev.emptyDirectory;
  }));
  nodes.machine = { lib, ... }: {
    imports = [ ../modules/sep.nix ];
    services.fprintd.package = fprintd;
    systemd.timers.aurora-sep.enable = false;
    systemd.services = {
      aurora-sep.path = lib.mkForce [ modinfo pkgs.gnugrep ];
      aurora-touchid-setup.environment.AURORA_TOUCHID_FILES = "/run/sep-fixture/touchid-files";
      aurora-sep-ready = {
        environment = {
          AURORA_SEP_SYSFS = "/run/sep-fixture/devices";
          AURORA_SEP_READY_WAIT = "2";
        };
        serviceConfig.ExecStartPre = pkgs.writeShellScript "trace-sep-readiness" ''
          echo ready >> /run/sep-fixture/events
        '';
      };
      fprintd.serviceConfig.Type = lib.mkForce "simple";
    };
  };
  testScript = builtins.readFile ./sep-lifecycle.py;
}
