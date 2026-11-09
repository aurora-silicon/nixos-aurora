{ pkgs, makeSystem }:
let
  inherit (pkgs) lib;
  system = (makeSystem "minimal").extendModules {
    modules = [ { boot.plymouth.enable = true; } ];
  };
  theme = toString system.pkgs.plymouth-theme-aurora;
  # Exercise the real initrd copier on the declared theme payload without
  # building the kernel and the rest of the boot environment.
  initrd = pkgs.makeInitrdNG {
    compressor = "zstd";
    contents = lib.filter (entry: entry.enable && lib.hasPrefix "${theme}/" entry.source)
      system.config.boot.initrd.systemd.storePaths;
  };
in pkgs.runCommand "aurora-plymouth-initrd" {
  nativeBuildInputs = [ pkgs.cpio pkgs.zstd ];
} ''
  mkdir unpacked
  cd unpacked
  zstd -dc < ${initrd}/initrd | cpio -id --quiet --no-absolute-filenames
  theme=.${theme}
  test -x "$theme/libexec/aurora-plymouth" || {
    echo 'initrd lacks the executable Aurora Plymouth geometry helper' >&2
    exit 1
  }
  for file in aurora.plymouth aurora.script aurora-logo-128.png aurora-logo-256.png; do
    test -s "$theme/share/plymouth/themes/aurora/$file" || {
      echo "initrd lacks the Aurora Plymouth theme file $file" >&2
      exit 1
    }
  done
  touch "$out"
''
