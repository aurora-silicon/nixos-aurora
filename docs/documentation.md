# Documentation

Describe behavior and constraints in module option declarations. Keep import instructions in [Modules](modules.md), and package-specific use in [Gaming](gaming.md). Historical build and PR notes belong in the [reference index](README.md).

## Generate the option reference

The reference includes every public `aurora.*` option from `nixosModules.default` and `nixosModules.installed`, including submodule fields. It records declared defaults, not one machine's configured values. Standard NixOS and Apple Silicon options are linked from the module guide.

```sh
nix eval --json .#checks.aarch64-linux.documentation.optionData > /tmp/aurora-options.json
python3 scripts/render-options.py /tmp/aurora-options.json > docs/options.md
nix build --no-link .#checks.aarch64-linux.documentation
```

The check rejects missing descriptions/source declarations and a stale checked-in reference. Its output contains `share/doc/aurora/options.md` and `share/doc/aurora/options.json`. To inspect it:

```sh
nix build --out-link result-docs .#checks.aarch64-linux.documentation
```

The JSON uses `nixosOptionsDoc` metadata: names, descriptions, types, defaults, examples and source links. Module exports preserve their file paths so indexers can locate declarations. No hardware packages are built for documentation.
CI builds the reference and uploads both files as the `aurora-documentation` artifact.

## Build the site

```sh
nix build --out-link out/documentation-site .#checks.aarch64-linux.documentation-site
```

The static site contains the guides and the NüschtOS option browser. Cache deployment builds it in parallel with cache verification, then publishes both in one Pages artifact. Documentation is served under `/nixos-aurora/docs/`; `source-revision.txt` records its source commit. Pull-request CI uploads a preview as `aurora-documentation-site`.
