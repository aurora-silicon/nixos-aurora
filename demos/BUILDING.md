# Build the optional demos

Use native aarch64 Linux. Build checks use synthetic buffers only, without
opening audio or camera devices. The three distributions use demos/sources.json
for the same immutable archives. Models are not needed by the fetcher package.

Fedora, in a disposable Fedora 44 builder with rpm-build and dnf5-plugins:

```sh
AURORA_INSTALL_BUILDDEPS=1 AURORA_BUILD_JOBS=6 bash scripts/build-rpm aurora-models
AURORA_INSTALL_BUILDDEPS=1 AURORA_BUILD_JOBS=6 bash scripts/build-rpm aurora-capture-ns
AURORA_INSTALL_BUILDDEPS=1 AURORA_BUILD_JOBS=6 bash scripts/build-rpm whisper-cpp-aurora
```

The capture recipe produces three packages. The helper verifies every archive
before staging it. Cargo uses the exact integration lock, including Tract
0.21.4; as with the existing Rust recipes, crate fetching requires network
access. Source RPMs retain the resolved dependency lock and original sources.

ALARM, as an unprivileged builder with base-devel and sudo pacman access:

```sh
MAKEFLAGS=-j6 bash scripts/build-package aurora-models
MAKEFLAGS=-j6 bash scripts/build-package aurora-capture-ns
MAKEFLAGS=-j6 bash scripts/build-package whisper-cpp-aurora
```

Each PKGBUILD also works directly in its package directory; shared local
sources are symlinked to demos/. The build and CI helpers dereference them
when staging a disposable build directory. The models helper is a runtime
dependency of Whisper, not a compiler dependency.

Nix in an aarch64-linux builder:

```sh
nix flake check --no-build
nix build --max-jobs 1 --cores 6 --print-build-logs .#aurora-models .#rnnoise .#libdf .#capture-ns .#whisper-cpp-aurora
```

No new package is added to an image profile automatically. The existing
camera package remains in its original packaging PR; this extension only
makes it opt-in until a public effects source pin is available. No build uses
a private checkout or downloads an Apple-compiled program.

Libane uses the source-only archive in demos/, with per-file immutable URLs and
SHA-256 hashes in demos/sources.json. Reproduce it with
`python3 demos/rebuild-libane-source.py --output /tmp/libane-source.tar.gz`.
The full upstream archive is not a package input: unrelated compiled fixtures
and firmware are excluded.

The libDF C API uses O2 without the upstream workspace's thin LTO. This is the
same release profile on all three distros; reference-Mac performance still
needs lead measurement. `CARGO_BUILD_JOBS` can limit Rust build parallelism.

Build `mil-hwx-compiler` with the same distro helper, or `nix build .#mil-hwx-compiler`. The compiler uses isolated modern GNUstep/libobjc2 (the exact three bootstrap revisions in sources.json), never the distro legacy ABI. `rebuild-compiler-source.py` recreates its source-only archive from the pinned public commit and verifies every selected text file. Software build checks exercise linked compilation without a device. Relocated RPM/Arch runtime still needs installed-package smoke validation.

The compiler builds `libane_python.so` from the separately hash-pinned public C bridge and installs the shared H13 graph runner. Whisper discovers this optional package through `mil-hwxc` on PATH. Missing runtime glue makes auto select Vulkan/CPU before starting inference. The ANE worker remains responsible for bundle hashes, shapes, H13 caps and resource ownership.
