{ stdenvNoCC, lib, fetchurl, makeWrapper, bash, cryptsetup, btrfs-progs, util-linux,
  coreutils, systemd, gawk, gnugrep, gnused, python3, shadow, sudo, kbd, glibc, procps }:
let
  pin = (builtins.fromJSON (builtins.readFile ./sources.json)).aurora-firstboot;
  rootTools = [ bash cryptsetup btrfs-progs util-linux coreutils systemd gawk gnugrep gnused ];
in stdenvNoCC.mkDerivation {
  pname = "aurora-firstboot";
  version = pin.version;
  src = fetchurl { name = "aurora-firstboot-${pin.commit}.tar.gz"; url = pin.source_url; hash = pin.nix_hash; };
  nativeBuildInputs = [ makeWrapper ];
  dontBuild = true;
  installPhase = ''
    runHook preInstall
    make install-common PREFIX=$out
    substituteInPlace $out/lib/aurora/aurora-initrd-root \
      --replace-fail /usr/lib/aurora/vendor/omarchy-mac-encrypt $out/lib/aurora/vendor/omarchy-mac-encrypt
    # The PAM hook runs the first-boot program from the store.
    substituteInPlace $out/lib/aurora/aurora-password-hook \
      --replace-fail /usr/lib/aurora/aurora-firstboot $out/lib/aurora/aurora-firstboot
    patchShebangs $out/lib/aurora
    wrapProgram $out/lib/aurora/aurora-initrd-root --prefix PATH : ${lib.makeBinPath rootTools}
    # The Plymouth client is the one the system runs (installed with
    # boot.plymouth.enable), so it is found in the system profile last.
    wrapProgram $out/lib/aurora/aurora-firstboot --prefix PATH : ${lib.makeBinPath (rootTools ++ [ python3 shadow sudo kbd glibc.getent procps ])} \
      --suffix PATH : /run/current-system/sw/bin
    # NixOS declares units through its modules rather than importing /usr paths.
    rm -r $out/lib/systemd
    runHook postInstall
  '';
  passthru.initrdInputs = map lib.getBin rootTools;
  meta.license = lib.licenses.mit;
}
