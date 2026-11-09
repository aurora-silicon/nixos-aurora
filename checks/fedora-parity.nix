{ pkgs, nixpkgs, self }:
let
  inherit (nixpkgs) lib;
  profiles = lib.attrValues self.nixosConfigurations;
  hasPatch = package: lib.any (patch: lib.hasSuffix "-alsactl-skip-locked-controls.patch" (toString patch))
    (package.patches or [ ]);
  failures = lib.concatMap (value: let inherit (value) config; in
    lib.mapAttrsToList (name: _: "${config.aurora.desktop}: ${name}")
      (lib.filterAttrs (_: passed: !passed) {
        "ALSA restore skips controls owned by another process" = hasPatch value.pkgs.alsa-utils
          && lib.elem value.pkgs.alsa-utils config.environment.systemPackages;
        "the Touch Bar runs tiny-dfr, as on Fedora and ALARM" = config.hardware.apple.touchBar.enable
          && lib.elem config.hardware.apple.touchBar.package config.services.udev.packages
          && lib.elem config.hardware.apple.touchBar.package config.systemd.packages;
        "Aurora artwork is installed on every profile" =
          lib.elem value.pkgs.aurora-logos config.environment.systemPackages;
        "Plasma About uses the immutable Aurora logo" = config.aurora.desktop != "kde"
          || lib.elem "LogoPath=${value.pkgs.aurora-logos}/share/pixmaps/system-logo-white.png"
            (lib.splitString "\n" config.environment.etc."xdg/kcm-about-distrorc".text);
        "early display audio carries the sequencer" = lib.elem "snd-seq" config.boot.initrd.availableKernelModules;
        "the Type-C port controllers find their USB4 router in the initrd" =
          lib.all (m: lib.elem m config.boot.initrd.availableKernelModules) [ "tps6598x" "thunderbolt_apple" ];
        "the display chain and its PMP come up before the root is unlocked" =
          lib.all (m: lib.elem m config.boot.initrd.availableKernelModules)
            [ "apple-pmp" "mux-apple-display-crossbar" "appledrm" ];
        "the PipeWire daemon carries the filter-graph volume and latency fixes" = let
          package = config.services.pipewire.package;
          patched = suffix: lib.any (patch: lib.hasSuffix suffix (toString patch)) (package.patches or [ ]);
        in package.doCheck
          && patched "-1005-filter-graph-follow-plugin-latency-after-activation.patch"
          && patched "-1006-filter-graph-keep-the-software-volume-at-unity-on-ev.patch"
          && patched "-1007-alsa-back-off-a-refused-snd_pcm_start-and-rate-limit.patch"
          && patched "-1008-alsa-a-start-on-a-suspended-PCM-is-expected-not-an-error.patch";
        "PipeWire and WirePlumber use the pinned audio and UCM profiles" =
          lib.elem value.pkgs.asahi-audio config.services.pipewire.configPackages
          && lib.elem value.pkgs.asahi-audio config.services.pipewire.wireplumber.configPackages
          && config.environment.variables.ALSA_CONFIG_UCM2 == "${value.pkgs.alsa-ucm-conf-asahi}/share/alsa/ucm2";
        "Mesa development and OpenCL interfaces match the native pin" =
          value.pkgs.mesa ? dev
          && value.pkgs.mesa.opencl.outPath == value.pkgs.aurora-rusticl.outPath
          && value.pkgs.mesa.auroraCommit == value.pkgs.aurora-rusticl.auroraCommit
          && lib.elem value.pkgs.mesa.opencl config.hardware.graphics.extraPackages;
        "CPU Vulkan is installed from the native Mesa pin" =
          value.pkgs.mesa.auroraCommit == value.pkgs.aurora-lavapipe.auroraCommit
          && lib.elem value.pkgs.aurora-lavapipe config.hardware.graphics.extraPackages;
        "FEX switches stop and remount the immutable layer" =
          config.systemd.services.aurora-fex-mesa.stopIfChanged
          && config.systemd.services.aurora-fex-mesa.restartIfChanged
          && lib.elem config.aurora.fexMesa.package config.systemd.services.aurora-fex-mesa.restartTriggers;
        "the camera denoise filter starts with every PipeWire session" = config.aurora.cameraDenoise.enable
          && config.services.pipewire.enable
          && lib.elem value.pkgs.aurora-camera-denoise config.systemd.packages
          && lib.elem "pipewire.service" config.systemd.user.services.aurora-camera-denoise.wantedBy;
        "the keyboard backlight follows the light sensor from boot" = config.aurora.kbdLight.enable
          && lib.elem value.pkgs.aurora-kbd-light config.systemd.packages
          && lib.elem "multi-user.target" config.systemd.services.aurora-kbd-light.wantedBy;
        "the sep-key group gets /dev/sep-key for Secure Enclave SSH keys" = config.users.groups ? sep-key
          && lib.elem value.pkgs.aurora-sep-sk config.services.udev.packages
          && lib.elem value.pkgs.aurora-sep-sk config.environment.systemPackages;
        "the Touch ID security key stays off unless asked for" = !config.aurora.fido.enable
          && !(config.systemd.services ? aurora-fido);
        "AirDrop over AWDL stays off unless asked for" = !config.aurora.awdl.enable
          && !(lib.elem value.pkgs.omdrop-awdl config.systemd.packages);
        "Flatpak uses the Aurora repository" = config.services.flatpak.enable
          && config.aurora.flatpak.enable
          && config.aurora.flatpak.package.commit == pkgs.aurora-flatpak-gl.commit
          && config.aurora.flatpak.package.commit == pkgs.aurora-fex-mesa.commit;
        "the image installs and pins GL before desktop login" =
          lib.elem "multi-user.target" config.systemd.services.aurora-flatpak-gl.wantedBy
          && lib.elem "display-manager.service" config.systemd.services.aurora-flatpak-gl.before;
        "shutdown keeps installed Flatpak runtimes" =
          config.systemd.services.aurora-flatpak-gl.unitConfig.DefaultDependencies == false;
        "FEX carries both guest architectures" = config.aurora.fexMesa.enable
          && lib.elem config.aurora.fexMesa.package config.environment.systemPackages;
        "drkonqi's user units do not deadlock a Plasma session stop" = config.aurora.desktop != "kde"
          || lib.all (name: let unit = config.systemd.user.units.${name}; in
            unit.overrideStrategy == "asDropin" && lib.hasInfix "DefaultDependencies=no" unit.text
            && lib.hasInfix "Before=shutdown.target" unit.text)
            [ "drkonqi-coredump-cleanup.timer" "drkonqi-sentry-postman.path" ];
        "all four malcontent overrides name their retirement fix" = lib.all (name:
          let unit = config.systemd.units."${name}.service"; in
          unit.overrideStrategy == "asDropin" && lib.hasInfix "af8226a7d3c3" unit.text
          && lib.hasInfix "SystemCallFilter=@signal" unit.text
          && (name == "malcontent-webd-update" || lib.hasInfix "SuccessExitStatus=71" unit.text))
          [ "malcontent-timerd" "malcontent-timer-extension-agent" "malcontent-webd" "malcontent-webd-update" ];
      })) profiles;
in pkgs.runCommand "aurora-fedora-parity-evaluation" {
  failures = lib.concatStringsSep "\n" failures;
} ''
  if [[ -n "$failures" ]]; then printf '%s\n' "$failures" >&2; exit 1; fi
  touch $out
''
