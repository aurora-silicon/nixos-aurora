# Development

Use the pinned inputs in `flake.lock`. `sources.json` owns hardware source pins; recipes derive versions from those pins.

```sh
nix flake check --no-build --all-systems
nix shell --inputs-from . nixpkgs#openssl nixpkgs#dtc -c python3 -m unittest discover -s tests
nix shell --inputs-from . nixpkgs#openssl -c python3 -m unittest discover -s tests/integration
nix build --no-link .#checks.aarch64-linux.statix .#checks.aarch64-linux.deadnix
nix build --no-link .#checks.aarch64-linux.documentation
nix build --no-link .#checks.aarch64-linux.profiles .#checks.aarch64-linux.module-composition
```

The separate integration suite requires Nix, Git, OpenSSL and localhost access. It registers a tiny input-addressed fixture in a temporary store to verify signed cache publication and channel assembly, and checks selective updater input changes in a temporary Git flake. It does not build through the redirected store or require user namespaces. CI requires OpenSSL for the signature tests.

Statix and Deadnix use the pinned nixpkgs versions. Only Statix's `repeated_keys` rule is disabled: dotted option paths are a style choice. [Regenerate the option reference](documentation.md) after changing option metadata.

`nix flake show` lists packages and checks. Build a package with `nix build .#kernel` or `nix build .#steam`. Hardware builds use native AArch64; `fex-mesa` is built on x86_64 for FEX's guest userspace.

The FEX overlay VM check exercises generation switches, rollback, disabling and recovery. First-boot and SEP VM checks exercise the PAM/LUKS rekey flow and service repair lifecycle. Steam packaging checks run the configured FHS launcher as an ordinary user in a NixOS VM, including page size, graphics dependencies and Proton precedence. Device boot and game compatibility require hardware testing.

## Layout

| Path | Purpose |
|---|---|
| `flake.nix` | Public modules, profiles, packages and checks |
| `overlay.nix`, `pkgs/` | Package selection and recipes |
| `modules/` | NixOS integration and option declarations |
| `checks/`, `tests/` | Nix checks and tool regression tests |
| `scripts/` | Images, source tracking and cache publication |
| `kernel/`, `locks/`, `sources.json` | Shared kernel configuration and source pins |

[Updates](updates.md) covers publishing and signing. [Reference notes](README.md) retain dated investigations and build evidence.
