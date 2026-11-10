# Aurora NixOS

NixOS modules and pinned Aurora packages for Apple Silicon. The [native installer](https://github.com/aurora-silicon/aurora-installer) provides KDE Plasma, GNOME and minimal images.

- [Modules](docs/modules.md): imports, defaults and system behavior.
- [Options](docs/options.md): every public Aurora option, with types, defaults and examples.
- [Gaming](docs/gaming.md): Steam, Aurora Play, native Proton and FEX.
- [Updates](docs/updates.md): installed-system updates, channels and recovery.
- [Development](docs/development.md): builds and checks.
- [Documentation](docs/documentation.md): option generation and site builds.
- [Reference notes](docs/README.md): hardware guides and historical investigations.

Use `nixosModules.default` with the pinned Apple Silicon module and both overlays. Add `nixosModules.installed` for update commands and checked Stage 2 updates. `nixosModules.image` is for the native installer's partition layout. See the [import example](docs/modules.md#existing-system).

The flake exposes `aurora-kde`, `aurora-gnome` and `aurora-minimal` NixOS configurations. Hardware packages are under `packages.aarch64-linux`; `fex-mesa` also has an `x86_64-linux` build output.

```sh
nix build .#kernel .#mesa .#steam
```

Firmware and calibration are read from the installed Mac; builds do not include per-device firmware. Images remain development releases; build checks alone do not establish device or game compatibility.
