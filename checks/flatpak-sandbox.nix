{ pkgs }:
pkgs.runCommand "aurora-flatpak-build-sandbox" {
  requiredSystemFeatures = [ "uid-range" ];
  nativeBuildInputs = [ pkgs.bubblewrap ];
} ''
  test "$(id -u)" = 0
  mkdir -p /homeless-shelter
  bwrap --unshare-user --unshare-net --ro-bind / / --proc /proc --dev /dev \
    ${pkgs.runtimeShell} -c 'test -d /homeless-shelter'
  touch $out
''
