{ pkgs, nixpkgs, makeSystem }:
let
  inherit (nixpkgs) lib;
  # Records every call and writes what `uki build` would: the initrd it was
  # given and the command line inputs, so the UKI's inputs can be checked.
  fake = pkgs.writeShellScriptBin "aurora-secboot" ''
    echo "$*" >> "$AURORA_FAKE_LOG"
    [[ $1 == --config ]] && shift 2
    case "$1 $2" in
      "uki build")
        shift 2
        kver=$1; shift
        while [[ $# -gt 0 ]]; do
          case $1 in
            --initrd) initrd=$2 ;;
            --cmdline-file) cmdline=$2 ;;
            --init) init=$2 ;;
            --os-release) osrel=$2 ;;
            --output) output=$2 ;;
          esac
          shift 2
        done
        { echo "kver=$kver init=$init os-release=''${osrel:-} cmdline=$(cat "$cmdline")"; cat "$initrd"; } > "$output.tmp"
        mv "$output.tmp" "$output"
        ;;
      "uki verify") exit "''${AURORA_FAKE_VERIFY:-0}" ;;
    esac
  '';
  base = makeSystem "minimal";
  withSettings = settings: (base.extendModules {
    modules = [ { aurora.secureBoot = { package = lib.mkDefault fake; } // settings; } ];
  }).config;
  off = base.config;
  on = withSettings { enable = true; };
  owner = withSettings { enable = true; keyOwner = "owner"; securePath = true; lockdown = "confidentiality"; generations = 2; };
  auroraSecure = withSettings { enable = true; securePath = true; };
  storeKeys = withSettings { enable = true; keyDir = "${builtins.storeDir}/keys"; };
  noAdopt = withSettings { adoptInstallerKey = false; };
  # The packaged aurora-secboot with keys and an ESP in the sandbox build
  # directory (/build), for a real ukify + sbsign round trip.
  real = (base.extendModules {
    modules = [ {
      boot.loader.efi.efiSysMountPoint = lib.mkForce "/build/real/esp";
      aurora.secureBoot = { enable = true; keyOwner = "owner"; securePath = true; keyDir = "/build/real/keys"; generations = 1; };
    } ];
  }).config;
  realOff = (base.extendModules {
    modules = [ {
      boot.loader.efi.efiSysMountPoint = lib.mkForce "/build/real/esp";
      aurora.secureBoot = { enable = true; keyOwner = "owner"; keyDir = "/build/real/keys"; generations = 1; };
    } ];
  }).config;
  realSecboot = "${real.aurora.secureBoot.package}/bin/aurora-secboot --config ${real.system.build.auroraSecureBootConfig}";
  failed = c: map (a: a.message) (lib.filter (a: !a.assertion) c.assertions);
  installCommands = c: c.boot.loader.grub.extraInstallCommands;
  hasHook = c: lib.hasInfix "aurora-secboot-install" (installCommands c);
  adopt = c: c.systemd.services.aurora-secboot-adopt;
  # SEP LUKS boot-chain policy.
  sepLuks = settings: (base.extendModules {
    modules = [ { aurora.sepLuks = { enable = true; } // settings; } ];
  }).config;
  audit = sepLuks { };
  require = sepLuks { bootChain = "require"; initrd.enable = true; };
in
assert lib.assertMsg (!off.aurora.secureBoot.enable && off.aurora.secureBoot.keyOwner == "aurora"
  && !off.aurora.secureBoot.securePath && off.aurora.secureBoot.lockdown == "integrity"
  && off.aurora.secureBoot.keyDir == "/var/lib/aurora/secboot/keys"
  && off.aurora.secureBoot.ukiBuild == "auto")
  "secure boot defaults: off, Aurora-managed keys, no secure path, lockdown=integrity";
assert lib.assertMsg (!(hasHook off) && !(off.environment.etc ? "aurora/secboot.conf"))
  "the bootloader install and /etc are untouched while the module is off";
assert lib.assertMsg ((adopt off).unitConfig.ConditionPathExists == "/boot/efi/aurora/secboot/stage2.key"
  && lib.hasSuffix " keys adopt" (adopt off).serviceConfig.ExecStart
  && builtins.elem "multi-user.target" (adopt off).wantedBy
  && !(noAdopt.systemd.services ? aurora-secboot-adopt))
  "the installer's Stage 2 key leaves the ESP at first boot, also without enable";
assert lib.assertMsg (hasHook on && on.environment.etc ? "aurora/secboot.conf" && failed on == [ ])
  "enable installs the hook and the config";
# The UKI hook runs after the Stage 2 refresh and GRUB's core image rebuild.
assert lib.assertMsg (lib.hasSuffix "aurora-secboot-install \"\${1:-}\"\n" (installCommands on)
  && lib.hasInfix "aurora-install-stage2" (installCommands on))
  "the UKI hook is the last bootloader install step";
assert lib.assertMsg (lib.any (lib.hasInfix "securePath needs keyOwner") (failed auroraSecure))
  "securePath under Aurora-managed keys fails evaluation, as aurora-secboot enable refuses it";
assert lib.assertMsg (failed owner == [ ]) "securePath with owner keys evaluates";
assert lib.assertMsg (lib.any (lib.hasInfix "must not be in the Nix store") (failed storeKeys))
  "keys in the Nix store are refused";
assert lib.assertMsg (audit.aurora.sepLuks.bootChain == "audit"
  && !(audit.boot.initrd.systemd.contents ? "/etc/aurora-sep/fde.conf")
  && require.boot.initrd.systemd.contents."/etc/aurora-sep/fde.conf".source
    == require.environment.etc."aurora-sep/fde.conf".source)
  "the boot-chain policy defaults to audit and the initrd carries the system's fde.conf";
let
  run = c: "${c.system.build.auroraSecureBootInstall}/bin/aurora-secboot-install";
in pkgs.runCommand "aurora-secure-boot-module" { } ''
  set -euo pipefail
  check() { if ! eval "$1"; then echo "FAIL: $2" >&2; exit 1; fi; }

  # Configuration files.
  conf=${on.system.build.auroraSecureBootConfig}
  for line in KEY_OWNER=aurora SECURE_PATH=no LOCKDOWN=integrity KEY_DIR=/var/lib/aurora/secboot/keys \
      ESP=/boot/efi UKI_BUILD=auto; do
    check "grep -qx $line $conf" "default config has $line"
  done
  conf=${owner.system.build.auroraSecureBootConfig}
  check "grep -qx KEY_OWNER=owner $conf && grep -qx SECURE_PATH=yes $conf && grep -qx LOCKDOWN=confidentiality $conf" \
    "owner config"
  check "grep -qx 'boot-chain = audit' ${audit.environment.etc."aurora-sep/fde.conf".source}" "fde.conf audit"
  check "grep -qx 'boot-chain = require' ${require.environment.etc."aurora-sep/fde.conf".source}" "fde.conf require"
  check "! grep -q 'boot-chain = audit' ${require.environment.etc."aurora-sep/fde.conf".source}" "one boot-chain line"
  check "grep -q '^recovery = ' ${require.environment.etc."aurora-sep/fde.conf".source}" "other fde.conf lines kept"

  # Five fake generations; generation 4 has initrd secrets.
  mkdir -p profiles esp/EFI/Linux esp/EFI/BOOT keys tmp
  for n in 1 2 3 4 5; do
    g=$PWD/store/$(printf 'h%031d' $n)-nixos-system-aurora-$n
    mkdir -p $g/kernel-modules/lib/modules/6.19.$n-aurora
    echo kernel$n > $g/kernel
    echo initrd$n > $g/initrd
    printf 'root=fstab systemd.debug_shell=1 loglevel=4' > $g/kernel-params
    touch $g/init
    ln -s $g profiles/system-$n-link
  done
  g4=$PWD/store/$(printf 'h%031d' 4)-nixos-system-aurora-4
  printf '#!${pkgs.runtimeShell}\necho SECRET >> "$1"\n' > $g4/append-initrd-secrets
  chmod +x $g4/append-initrd-secrets
  default=$PWD/profiles/system-5-link
  mkdir -p $default/etc && echo 'PRETTY_NAME="NixOS gen 5"' > $default/etc/os-release
  uki() { echo "$PWD/esp/EFI/Linux/aurora-nixos-$(printf 'h%031d' $1).efi"; }
  export AURORA_SECBOOT_ESP=$PWD/esp AURORA_SECBOOT_PROFILES=$PWD/profiles AURORA_SECBOOT_TMP=$PWD/tmp \
    AURORA_SECBOOT_KEY_DIR=$PWD/keys AURORA_FAKE_LOG=$PWD/log

  # auto without db.key: nothing is built, and stale UKIs of this module go.
  touch esp/EFI/Linux/aurora-nixos-stale.efi esp/EFI/Linux/other.efi
  : > log
  ${run on} $default
  check "[[ ! -s log ]]" "no calls without a key"
  check "[[ ! -e esp/EFI/Linux/aurora-nixos-stale.efi && -e esp/EFI/Linux/other.efi ]]" "only our stale UKIs removed"

  # With db.key: generations 3, 4 and 5 (5 is also the default), once each.
  touch keys/db.key
  : > log
  ${run on} $default
  check "[[ $(grep -c ' uki build ' log) == 3 ]]" "three UKIs built"
  check "grep -q -- '^--config ${on.system.build.auroraSecureBootConfig} uki build 6.19.5-aurora --image .*-nixos-system-aurora-5/kernel --initrd ' log" "config, kernel version and image"
  check "grep -q -- '--init .*-nixos-system-aurora-5/init --os-release .*-nixos-system-aurora-5/etc/os-release --output $(uki 5)' log && grep -q -- '--init .*-nixos-system-aurora-4/init --output $(uki 4)' log" "init=, os-release and per-generation output"
  check "[[ ! -e $(uki 1) && ! -e $(uki 2) && -e $(uki 3) ]]" "only the listed generations"
  check "grep -qx SECRET $(uki 4) && ! grep -q SECRET $(uki 3)" "initrd secrets appended to their generation only"
  check "grep -q 'cmdline=root=fstab systemd.debug_shell=1 loglevel=4' $(uki 5)" "kernel-params go to the CLI, which filters them"
  check "grep -q 'os-release=.*-nixos-system-aurora-5/etc/os-release ' $(uki 5) && grep -q 'os-release= ' $(uki 4)" \
    "the generation's os-release when it has one"
  check "! grep -q ' enable\| disable' log" "no secure path changes when it is off"
  check "[[ -z \"$(find tmp -mindepth 1)\" ]]" "temporary initrds removed"

  # Unchanged and verified: no rebuild. Not verified (key changed): rebuilt.
  touch keys/db.crt
  : > log
  ${run on} $default
  check "[[ $(grep -c ' uki build ' log) == 0 && $(grep -c ' uki verify ' log) == 3 ]]" "verified UKIs kept"
  : > log
  AURORA_FAKE_VERIFY=1 ${run on} $default
  check "[[ $(grep -c ' uki build ' log) == 3 ]]" "UKIs re-signed after a key change"

  # Secure path: the default generation's UKI becomes BOOTAA64.EFI.
  : > log
  ${run owner} $PWD/profiles/system-4-link
  check "grep -q -- ' enable --uki $(uki 4)$' log" "enable with the default generation's UKI"
  check "[[ -e $(uki 4) && -e $(uki 5) && ! -e $(uki 3) ]]" "generations = 2 plus the default"

  # Secure path off again: GRUB goes back.
  touch esp/EFI/BOOT/BOOTAA64.EFI.aurora-shim
  : > log
  ${run on} $default
  check "grep -q ' disable$' log" "disable when a previous generation had the secure path"

  # No key at all: ukiBuild = auto removes our UKIs; the hook never fails the install.
  rm keys/db.key keys/db.crt esp/EFI/BOOT/BOOTAA64.EFI.aurora-shim
  ${run on} $default
  check "[[ -z \"$(find esp/EFI/Linux -name 'aurora-nixos-*')\" ]]" "UKIs removed without a key"

  # Real round trip: owner keys from `keys create`, a UKI from ukify + sbsign
  # (the systemd stub stands in for the kernel: any PE image will do), then
  # sbverify against db.crt and the secure path switched on and off.
  check "[[ -w /build ]]" "the sandbox build directory is /build"
  r=/build/real
  g=$r/store/$(printf 'r%031d' 1)-nixos-system-real
  mkdir -p $r/profiles $r/esp/EFI/BOOT $r/tmp $g/kernel-modules/lib/modules/6.19.0-aurora
  cp ${real.aurora.secureBoot.package.stub} $g/kernel
  echo initrd > $g/initrd
  printf 'root=fstab systemd.debug_shell=1 panic=10 loglevel=4' > $g/kernel-params
  touch $g/init
  mkdir -p $g/etc && echo 'PRETTY_NAME="Aurora NixOS round trip"' > $g/etc/os-release
  ln -s $g $r/profiles/system-1-link
  echo GRUB > $r/esp/EFI/BOOT/BOOTAA64.EFI
  ${realSecboot} keys create
  env AURORA_SECBOOT_ESP=$r/esp AURORA_SECBOOT_PROFILES=$r/profiles AURORA_SECBOOT_TMP=$r/tmp \
    AURORA_SECBOOT_KEY_DIR= ${run real} $r/profiles/system-1-link
  realUki=$r/esp/EFI/Linux/aurora-nixos-$(printf 'r%031d' 1).efi
  check "${realSecboot} uki verify $realUki | grep -q ': verified$'" "the UKI verifies against db.crt"
  check "cmp -s $realUki $r/esp/EFI/BOOT/BOOTAA64.EFI && [[ $(cat $r/esp/EFI/BOOT/BOOTAA64.EFI.aurora-shim) == GRUB ]]" \
    "the UKI is BOOTAA64.EFI and GRUB is kept"
  check "grep -aq 'init=$g/init lockdown=integrity' $realUki && ! grep -aq systemd.debug_shell $realUki && ! grep -aq panic= $realUki" \
    "signed command line: init= and lockdown=integrity, no shell or lab settings"
  check "grep -aq 'Aurora NixOS round trip' $realUki" "the UKI carries the generation's os-release"
  sha256sum $realUki
  env AURORA_SECBOOT_ESP=$r/esp AURORA_SECBOOT_PROFILES=$r/profiles AURORA_SECBOOT_TMP=$r/tmp \
    AURORA_SECBOOT_KEY_DIR= ${run realOff} $r/profiles/system-1-link
  check "[[ $(cat $r/esp/EFI/BOOT/BOOTAA64.EFI) == GRUB && ! -e $r/esp/EFI/BOOT/BOOTAA64.EFI.aurora-shim ]]" \
    "turning the secure path off puts GRUB back"
  rm -rf $r/keys
  touch $out
''
