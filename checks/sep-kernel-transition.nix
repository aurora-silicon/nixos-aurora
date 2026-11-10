{ pkgs, imageProbe }:
pkgs.runCommand "aurora-sep-running-kernel-check" {
  nativeBuildInputs = [ pkgs.python3 pkgs.gnugrep ];
  sepCondition = imageProbe.config.systemd.services.aurora-sep.serviceConfig.ExecCondition;
  probeShell = pkgs.runtimeShell;
} ''
  python3 ${./sep-kernel-transition.py}
  touch $out
''
