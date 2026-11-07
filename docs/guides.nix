{ pkgs, documentation }:
let
  source = pkgs.lib.fileset.toSource {
    root = ./.;
    fileset = pkgs.lib.fileset.fileFilter
      (file: file.hasExt "md" || file.hasExt "json") ./.;
  };
in pkgs.runCommand "aurora-documentation-guides" {
  nativeBuildInputs = [ pkgs.mkdocs ];
} ''
  mkdir content
  cp -r ${source}/. content/
  chmod -R u+w content
  mv content/README.md content/reference.md
  rm content/options.md
  cp ${documentation}/share/doc/aurora/options.md content/options-reference.md
  cp ${./site-links.py} site-links.py
  cp ${./mkdocs.yml} mkdocs.yml
  mkdocs build --strict --site-dir "$out"
''
