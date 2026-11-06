{ pkgs }:
let
  source = pkgs.lib.fileset.toSource {
    root = ../.;
    fileset = pkgs.lib.fileset.fileFilter
      (file: file.hasExt "nix" || file.name == "statix.toml") ../.;
  };
in {
  statix = pkgs.runCommand "aurora-statix" { nativeBuildInputs = [ pkgs.statix ]; } ''
    cd ${source}
    statix check . --config statix.toml
    touch "$out"
  '';
  deadnix = pkgs.runCommand "aurora-deadnix" { nativeBuildInputs = [ pkgs.deadnix ]; } ''
    deadnix --fail ${source}
    touch "$out"
  '';
}
