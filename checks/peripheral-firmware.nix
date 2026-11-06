{ pkgs, nixpkgs, self }:
let
  tools = import ../firmware/package.nix { inherit pkgs; };
  probe = nixpkgs.lib.nixosSystem {
    system = pkgs.stdenv.hostPlatform.system;
    modules = [
      self.inputs.apple-silicon.nixosModules.default
      ../modules/firmware.nix
      {
        nixpkgs.overlays = [ self.inputs.apple-silicon.overlays.default self.overlays.default ];
        hardware.asahi.enable = true;
        system.stateVersion = "26.05";
      }
    ];
  };
  cfg = probe.config;
  executable = "${tools.loadFirmware}/bin/aurora-load-vendor-firmware";
in
assert builtins.elem "dockchannel-hid" cfg.boot.initrd.availableKernelModules;
assert builtins.elem "dockchannel-hid" cfg.boot.blacklistedKernelModules;
assert cfg.boot.initrd.systemd.services.aurora-vendor-firmware.serviceConfig.ExecStart == executable;
assert cfg.systemd.services.aurora-vendor-firmware.serviceConfig.ExecStart == "${executable} runtime";
assert builtins.all (tool: builtins.any (entry: toString entry.source == toString tool)
  cfg.boot.initrd.systemd.storePaths)
  [ tools.loadFirmware tools.extractFirmware tools.admission ];
pkgs.runCommand "aurora-peripheral-firmware-check" { nativeBuildInputs = [ pkgs.bash ]; } ''
  # Building these outputs also checks the installed wrappers with ShellCheck.
  test -x ${executable}
  test -x ${tools.extractFirmware}/bin/aurora-extract-vendor-firmware
  test -x ${tools.admission}/bin/aurora-peripheral-admission
  bash -n ${executable}
  bash -n ${tools.extractFirmware}/bin/aurora-extract-vendor-firmware
  printf 'invalid-partition-uuid\0' > efi-property
  printf 'apple,j413\0apple,t8112\0' > compatible
  cat > modprobe <<'SH'
  #!${pkgs.runtimeShell}
  echo "$1" >> "$AURORA_TEST_CALLS"
  SH
  chmod +x modprobe
  mkdir system-firmware
  touch parameter
  export AURORA_EFI_PROPERTY="$PWD/efi-property" AURORA_DT_COMPATIBLE="$PWD/compatible"
  export AURORA_FIRMWARE_DESTINATION="$PWD/destination" AURORA_MODPROBE="$PWD/modprobe"
  export AURORA_FIRMWARE_FALLBACK="$PWD/fallback" AURORA_SYSTEM_FIRMWARE="$PWD/system-firmware"
  export AURORA_FIRMWARE_PARAMETER="$PWD/parameter" AURORA_TEST_CALLS="$PWD/module-calls"
  # The installed wrapper must find both helpers through its packaged PATH.
  # A failed extraction still admits the keyboard; runtime reports that error.
  ${executable} initrd
  printf 'dockchannel-hid\naop\n' > expected-calls
  diff -u expected-calls module-calls
  : > module-calls
  status=0
  ${executable} runtime || status=$?
  test "$status" = 1
  diff -u expected-calls module-calls
  test "$(cat parameter)" = "$PWD/destination/vendorfw"
  test "$(readlink fallback)" = "$PWD/system-firmware"
  touch $out
''
