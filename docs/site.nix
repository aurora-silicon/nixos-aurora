{ pkgs, self, system }:
let
  documentation = self.checks.${system}.documentation;
  guides = import ./guides.nix { inherit pkgs documentation; };
  # ixx interprets string declarations as store paths. Its URL object form
  # preserves the portable declaration links in our generated options JSON.
  browserOptions = pkgs.runCommand "aurora-search-options.json" {
    nativeBuildInputs = [ pkgs.python3 ];
  } ''
    python3 - ${documentation}/share/doc/aurora/options.json "$out" <<'PY'
    import json
    import sys
    with open(sys.argv[1]) as source:
        options = json.load(source)
    for option in options.values():
        option["declarations"] = [{"name": url, "url": url} for url in option["declarations"]]
    with open(sys.argv[2], "w") as output:
        json.dump(options, output)
    PY
  '';
  options = (self.inputs.nuschtos-search.packages.${system}.mkSearch {
    optionsJSON = browserOptions;
    title = "Aurora NixOS";
    baseHref = "/nixos-aurora/docs/options/";
    hashLocation = true;
    # This scope has no package results needing Nixpkgs' metadata tables.
    licenses = { };
    maintainers = { };
    teams = { };
    # The indexer requires a base URL; absolute declaration URLs retain theirs.
    urlPrefix = "https://github.com/aurora-silicon/nixos-aurora/blob/main/";
  }).overrideAttrs (previous: {
    # This input follows our nixpkgs; its fetchPnpmDeps normalization differs
    # from the upstream nuschtpkgs revision used for the original dependency hash.
    pnpmDeps = previous.pnpmDeps.overrideAttrs {
      outputHash = "sha256-iC9dSmrqdx/4Lg68K6vqI+DstguW2Vnf0KLNX1aEfK8=";
    };
  });
  revision = self.rev or self.dirtyRev or "worktree";
in pkgs.runCommand "aurora-documentation-site" {
  nativeBuildInputs = [ pkgs.python3 ];
  passthru = { inherit guides options; };
} ''
  mkdir -p $out/options
  cp -r ${guides}/. $out/
  cp -r ${options}/. $out/options/
  printf '%s\n' ${pkgs.lib.escapeShellArg revision} > $out/source-revision.txt
  test -s $out/index.html
  test -s $out/options/index.html
  python3 - ${documentation}/share/doc/aurora/options.json "$out/options/data/options/chunks" <<'PY'
  import json
  import pathlib
  import sys
  with open(sys.argv[1]) as source:
      expected = json.load(source)
  indexed = []
  for chunk in pathlib.Path(sys.argv[2]).glob("*.json"):
      with chunk.open() as source:
          indexed.extend(json.load(source))
  names = [option["name"] for option in indexed]
  assert len(names) == len(set(names)), "duplicate indexed option names"
  assert set(names) == set(expected), "browser index does not contain every documented option"
  for option in indexed:
      assert option["declarations"] == expected[option["name"]]["declarations"], option["name"]
  PY
''
