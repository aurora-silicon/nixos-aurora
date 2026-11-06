{ pkgs }:
let
  custom = pkgs.m1n1.override { customLogo = ../logos/AuroraLogo-256.png; };
in
assert pkgs.lib.assertMsg (custom.drvPath != pkgs.m1n1.drvPath
  && builtins.elem "BUILTIN_LOGO=custom" custom.makeFlags)
  "Aura must honor customLogo instead of silently retaining the stock logo";
# Aura's build verifies the selected 48/128/256 px logos in both builds.
pkgs.runCommand "aurora-custom-boot-logo" { } ''
  test -s ${custom}/lib/m1n1/m1n1.bin
  test -s ${custom}/share/aura/stage1/aura-raw.bin
  touch $out
''
