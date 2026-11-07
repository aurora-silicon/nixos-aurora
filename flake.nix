{
  description = "Aurora NixOS for Apple Silicon";
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/1d060086d60cb76a40cf37109f979d88a5bd6396";
    apple-silicon.url = "github:nix-community/nixos-apple-silicon/12cd234285d3037cedfab979aa70b75284a59afc";
    apple-silicon.inputs.nixpkgs.follows = "nixpkgs";
  };
  outputs = { self, nixpkgs, apple-silicon, ... }:
    let
      system = "aarch64-linux";
      overlays = [ apple-silicon.overlays.default self.overlays.default ];
      pkgs = import nixpkgs {
        inherit system overlays;
        # Steam's ARM64 runtime includes GTK 2; retain its deprecation warning.
        # Remove this exception when Steam no longer needs GTK 2.
        # https://github.com/NixOS/nixpkgs/issues/410814
        config.problems.handlers."gtk+".broken = "warn";
      };
      makeSystem = desktop: nixpkgs.lib.nixosSystem {
        inherit system;
        modules = [ apple-silicon.nixosModules.default self.nixosModules.default
          { nixpkgs.overlays = overlays; aurora.desktop = desktop; }
          ./modules/image.nix ];
      };
      imageProbe = (makeSystem "minimal").extendModules {
        modules = [ self.nixosModules.installed ({ lib, ... }: { aurora.imageLayout = lib.mkForce {
          rootUUID = "eb688499-cc41-4c4c-b00b-dbf33e05427c";
          bootUUID = "3429647d-29a2-411c-8924-2545fda1ec34";
          efiUUID = "1E08-14ED";
        }; }) ];
      };
    in {
      overlays.default = import ./overlay.nix;
      nixosModules.image = import ./modules/image.nix;
      nixosModules.default = import ./modules/aurora.nix;
      # An installed system: the native installer provisioned Stage 1, which
      # rebuilds never touch; every bootloader install refreshes the ESP
      # Stage 2 as update-m1n1 does on ALARM and Fedora (modules/installed.nix).
      nixosModules.installed = import ./modules/installed.nix;
      nixosConfigurations = {
        aurora-kde = makeSystem "kde";
        aurora-gnome = makeSystem "gnome";
        aurora-minimal = makeSystem "minimal";
      };
      packages.${system} = {
        logos = pkgs.aurora-logos;
        plymouth = pkgs.plymouth;
        plymouth-theme-aurora = pkgs.plymouth-theme-aurora;
        firstboot = pkgs.aurora-firstboot;
        power-budget = pkgs.aurora-power-budget;
        docker = pkgs.docker;
        sep = pkgs.aurora-sep;
        libfprint = pkgs.libfprint;
        fprintd = pkgs.fprintd;
        avd-fw = pkgs.aurora-avd-firmware;
        libva-v4l2-request-avd = pkgs.libvaV4l2RequestAvd;
        omarchy-ane-tools = pkgs.omarchy-ane-tools;
        mil-hwx-compiler = pkgs.mil-hwx-compiler;
        upower = pkgs.upower;
        bindgen = pkgs.aurora-bindgen;
        aura = pkgs.m1n1;
        uboot = pkgs.uboot-asahi;
        kernel = pkgs.linux-asahi.kernel;
        userpages = pkgs.aurora-userpages;
        fex = pkgs.fex;
        steam = pkgs.steam;
        mesa = pkgs.mesa;
        rusticl = pkgs.aurora-rusticl;
        lavapipe = pkgs.aurora-lavapipe;
        graphics = pkgs.buildEnv {
          name = "aurora-graphics-interfaces";
          paths = [ pkgs.mesa pkgs.mesa.dev pkgs.aurora-rusticl pkgs.aurora-lavapipe ];
          pathsToLink = [ "/lib" "/include" "/etc" "/share" ];
          postBuild = ''
            cmp ${pkgs.mesa}/.aurora-mesa-commit ${pkgs.aurora-rusticl}/.aurora-mesa-commit
            cmp ${pkgs.mesa}/.aurora-mesa-commit ${pkgs.aurora-lavapipe}/.aurora-mesa-commit
            cp ${pkgs.mesa}/.aurora-mesa-commit $out/.aurora-mesa-commit
          '';
        };
        alsa-utils = pkgs.aurora-alsa-utils;
        pipewire = pkgs.aurora-pipewire;
        audio = pkgs.asahi-audio;
        ucm = pkgs.alsa-ucm-conf-asahi;
        fex-mesa = pkgs.aurora-fex-mesa;
        flatpak-gl = pkgs.aurora-flatpak-gl;
        speakerguardd = pkgs.speakerguardd;
        speakerguardd-v2 = pkgs.speakerguardd-v2;
        mutter = pkgs.mutter;
        speakersafetyd = pkgs.speakersafetyd;
        bankstown = pkgs.bankstown-lv2;
        neo-platform = pkgs.aurora-neo-platform-config;
        aurora-bless = pkgs.aurora-bless;
        camera-denoise = pkgs.aurora-camera-denoise;
        kbd-light = pkgs.aurora-kbd-light;
      };
      # The payload runs in an ARM machine's x86 guest, and is built on x86.
      packages.x86_64-linux.fex-mesa = pkgs.aurora-fex-mesa;
      checks.${system} = {
      clean-boot = let
        inherit (nixpkgs) lib;
        profiles = lib.attrValues self.nixosConfigurations;
        valid = lib.versionAtLeast pkgs.bluez.version "5.87"
          && lib.any (patch: lib.hasSuffix "docker-query-forwarding-policy.patch" (toString patch))
            (pkgs.docker.moby.patches or [ ])
          && pkgs.docker.moby.doCheck
          && lib.all (profile: let unit = profile.config.systemd.units."var-swap-swapfile2.swap"; in
            unit.overrideStrategy == "asDropin"
            && lib.hasInfix "After=var-swap-swapfile.swap" unit.text) profiles;
      in assert lib.assertMsg valid "Aurora clean-boot packaging parity failed";
        pkgs.runCommandNoCC "aurora-clean-boot-defaults" { } "touch $out";

      # speakerguardd 1.0 is installed on every Mac with the fleet gate on both
      # stacks; enable = false removes it and its gate.
      speakerguardd-v2-gated = let
        inherit (nixpkgs) lib;
        probe = extra: ((makeSystem "minimal").extendModules { modules = [ extra ]; }).config;
        on = probe { };
        off = probe { aurora.speakerguardd.v2.enable = false; };
        # The system's own build: its nixpkgs instance is not the flake's
        # pkgs, so the store paths differ.
        pkg = c: c.aurora.speakerguardd.v2.package;
        has = c: (pkg c).pname == "speakerguardd-v2"
          && builtins.elem (pkg c) c.environment.systemPackages
          && builtins.elem (pkg c) c.systemd.packages;
        unit = c: name: c.systemd.units.${name} or { enable = true; wantedBy = [ ]; text = ""; };
        wanted = c: name: builtins.elem "multi-user.target" (unit c name).wantedBy;
        # A plain string: hasInfix cannot take a pattern that refers to a
        # store path.
        gate = builtins.unsafeDiscardStringContext "${pkg on}/libexec/speakerguardd-v2/speakerguardd-gate legacy";
        gated = c: name: lib.hasInfix "ExecCondition=${gate}" (unit c "${name}.service").text;
      in assert lib.assertMsg (has on) "speakerguardd 1.0 must be installed by default";
         assert lib.assertMsg (wanted on "speakerguardd-v2.service") "speakerguardd-v2.service must be wanted by multi-user.target";
         assert lib.assertMsg (wanted on "speakerguardd-v2-seat.path") "speakerguardd-v2-seat.path must be wanted by multi-user.target";
         assert lib.assertMsg ((unit on "speakersafetyd.service").enable && (unit on "speakerguardd.service").enable
             && gated on "speakersafetyd" && gated on "speakerguardd")
           "the older daemons must stay installed and enabled, behind the fleet gate";
         assert lib.assertMsg (lib.hasInfix "use-feedback-guard" (unit on "speakersafetyd.service").text)
           "the gate must not replace speakersafetyd's own ExecCondition";
         assert lib.assertMsg (!has off && !wanted off "speakerguardd-v2.service"
             && !gated off "speakersafetyd" && !gated off "speakerguardd")
           "enable = false must remove speakerguardd 1.0 and its gate";
         pkgs.runCommand "speakerguardd-v2-package-check" { } ''
           p=${pkgs.speakerguardd-v2}
           lx=$p/libexec/speakerguardd-v2
           test -x $lx/speakerguardd
           test -x $lx/speakerguardd-provision
           test -x $lx/speakerguardd-gate
           test -x $p/bin/aurora-speaker-tuning
           test -f $p/lib/lv2/sgv2.lv2/manifest.ttl
           test -f $p/lib/lv2/sgv2.lv2/libsgv2_lv2.so
           test -f $p/share/speakerguardd/gate.json
           grep -qx "ExecStart=$lx/speakerguardd \$SGV2_ARGS" $p/lib/systemd/system/speakerguardd-v2.service
           grep -qx "ExecStart=$lx/speakerguardd-provision run" $p/lib/systemd/system/speakerguardd-v2-provision.service
           test -f $p/lib/systemd/system/speakerguardd-v2-seat.path
           test -f $p/lib/systemd/user/speakerguardd-v2-graph.service
           grep -q "$p/share/speakerguardd/gate.json" $lx/speakerguardd-gate
           test -f $lx/wiring.py
           test ! -e $p/share/speakerguardd/machines.json
           test ! -e $p/bin/speakerguardd
           touch $out
         '';

      ane-packaging = let
        firmware = pkgs.runCommand "ane-test-firmware" { } ''
          mkdir -p "$out/lib/firmware/apple/ane"
          echo 'synthetic packaging test marker; no firmware' > "$out/lib/firmware/apple/ane/test-marker"
        '';
        probe = nixpkgs.lib.nixosSystem {
          inherit system;
          modules = [ ./modules/ane.nix {
            nixpkgs.overlays = overlays;
            aurora.ane.enable = true;
            aurora.ane.firmwarePackage = firmware;
          } ];
        };
        cfg = probe.config;
      in assert cfg.users.groups ? accel;
         assert builtins.elem probe.pkgs.omarchy-ane-tools cfg.services.udev.packages;
         assert builtins.elem probe.pkgs.mil-hwx-compiler cfg.environment.systemPackages;
         pkgs.runCommand "ane-firmware-and-udev-check" { } ''
           test -f ${cfg.hardware.firmware}/lib/firmware/apple/ane/test-marker
           test ! -f ${cfg.hardware.firmware}/lib/firmware/apple/ane/test-marker.zst
           grep -F 'GROUP="accel", MODE="0660"' ${pkgs.omarchy-ane-tools}/lib/udev/rules.d/70-omarchy-ane.rules
           touch $out
         '';

      # Touch ID: which PAM services take a fingerprint, and the power button.
      touchid-pam = let
        inherit (nixpkgs) lib;
        auth = c: name: lib.filter (lib.hasPrefix "auth ")
          (lib.splitString "\n" (c.security.pam.services.${name}.text or ""));
        offers = c: name: lib.any (lib.hasInfix "/pam_fprintd.so") (auth c name);
        # pam_fprintd only as "sufficient", with the password after it.
        orPassword = c: name: let
          lines = auth c name;
          index = lib.lists.findFirstIndex (lib.hasInfix "/pam_fprintd.so") null lines;
        in index != null
          && lib.all (line: !(lib.hasInfix "/pam_fprintd.so" line) || lib.hasPrefix "auth sufficient " line) lines
          && lib.any (lib.hasInfix "/pam_unix.so") (lib.drop index lines);
        failures = lib.concatMap (value: let c = value.config; kde = c.aurora.desktop == "kde"; in
          lib.mapAttrsToList (name: _: "${c.aurora.desktop}: ${name}") (lib.filterAttrs (_: passed: !passed) {
            "sudo takes a fingerprint or the password" = orPassword c "sudo";
            "polkit takes a fingerprint or the password" = orPassword c "polkit-1";
            "the console login, su and ssh ask for the password" =
              !(offers c "login") && !(offers c "su") && !(offers c "sshd");
            "the login screen asks for the password" = if kde
              then !(offers c "plasmalogin") && !(offers c "kde")
              else c.aurora.desktop != "gnome" || !(offers c "gdm-password");
            "the lock screen takes a fingerprint" = if kde then offers c "kde-fingerprint"
              else c.aurora.desktop != "gnome" || offers c "gdm-fingerprint";
            "a short power-button press suspends" = c.services.logind.settings.Login.HandlePowerKey == "suspend"
              && c.services.logind.settings.Login.HandlePowerKeyLongPress == "poweroff"
              && (!kde || lib.hasInfix "PowerButtonAction=1" (builtins.readFile c.environment.etc."xdg/powerdevilrc".source));
          })) (lib.attrValues self.nixosConfigurations);
      in assert lib.assertMsg (failures == [ ]) "Touch ID PAM policy: ${lib.concatStringsSep "; " failures}";
        pkgs.runCommand "aurora-touchid-pam" { } "touch $out";

      fex-overlay-upgrade = import ./checks/fex-overlay-upgrade.nix { inherit pkgs; };
      flatpak-sandbox = pkgs.runCommand "aurora-flatpak-build-sandbox" {
        requiredSystemFeatures = [ "uid-range" ];
        nativeBuildInputs = [ pkgs.bubblewrap ];
      } ''
        test "$(id -u)" = 0
        mkdir -p /homeless-shelter
        bwrap --unshare-user --unshare-net --ro-bind / / --proc /proc --dev /dev \
          ${pkgs.runtimeShell} -c 'test -d /homeless-shelter'
        touch $out
      '';
      fedora-parity = let
        inherit (nixpkgs) lib;
        profiles = lib.attrValues self.nixosConfigurations;
        hasPatch = package: lib.any (patch: lib.hasSuffix "-alsactl-skip-locked-controls.patch" (toString patch))
          (package.patches or [ ]);
        failures = lib.concatMap (value: let config = value.config; in
          lib.mapAttrsToList (name: _: "${config.aurora.desktop}: ${name}")
            (lib.filterAttrs (_: passed: !passed) {
              "ALSA restore skips controls owned by another process" = hasPatch value.pkgs.alsa-utils
                && lib.elem value.pkgs.alsa-utils config.environment.systemPackages;
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
                && patched "-1007-alsa-back-off-a-refused-snd_pcm_start-and-rate-limit.patch";
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
      '';
      sep-kernel-transition = pkgs.runCommand "aurora-sep-running-kernel-check" {
        nativeBuildInputs = [ pkgs.python3 pkgs.gnugrep ];
        sepCondition = imageProbe.config.systemd.services.aurora-sep.serviceConfig.ExecCondition;
        probeShell = pkgs.runtimeShell;
      } ''
        python3 ${./checks/sep-kernel-transition.py}
        touch $out
      '';

      # The installed system's checked Stage 2, built from the same inputs as
      # the image's m1n1/boot.bin (the MacBook Neo's device tree included).
      # It needs the kernel, so the image workflow builds it next to the system.
      stage2 = imageProbe.config.system.build.auroraStage2;
      stage2-tools = imageProbe.config.system.build.auroraStage2Tools;
      # Per-process 4K userspace pages are on in every profile; an owner can
      # turn them off with user4k=off or aurora.userpages.enable = false.
      userpages = let
        inherit (nixpkgs) lib;
        profiles = lib.attrValues self.nixosConfigurations;
        kdeWith = module: (self.nixosConfigurations.aurora-kde.extendModules { modules = [ module ]; }).config;
        optedOut = kdeWith { boot.kernelParams = [ "user4k=off" ]; };
        disabled = kdeWith { aurora.userpages.enable = false; };
        position = argument: lib.lists.findFirstIndex (value: value == argument) (-1);
        expectations = {
          "every profile boots with user4k=on and ships the launcher" = lib.all (value:
            lib.elem "user4k=on" value.config.boot.kernelParams
            && lib.elem value.pkgs.aurora-userpages value.config.environment.systemPackages) profiles;
          "an owner's user4k=off follows user4k=on, so it wins" =
            position "user4k=on" optedOut.boot.kernelParams >= 0
            && position "user4k=on" optedOut.boot.kernelParams < position "user4k=off" optedOut.boot.kernelParams;
          "aurora.userpages.enable = false leaves out both" = !(lib.elem "user4k=on" disabled.boot.kernelParams)
            && !(lib.elem pkgs.aurora-userpages disabled.environment.systemPackages);
          "the launcher builds from the kernel's own source" =
            pkgs.aurora-userpages.src.outPath == pkgs.linux-asahi.kernel.src.outPath;
        };
      in pkgs.runCommand "aurora-userpages-evaluation" {
        failures = lib.concatStringsSep "\n" (lib.attrNames (lib.filterAttrs (_: met: !met) expectations));
      } ''
        if [[ -n "$failures" ]]; then printf '%s\n' "$failures" >&2; exit 1; fi
        ${pkgs.aurora-userpages}/bin/userpages --help > /dev/null
        touch $out
      '';
      firstboot-image = let
        inherit (nixpkgs) lib;
        kde = self.nixosConfigurations.aurora-kde.config;
        gnome = self.nixosConfigurations.aurora-gnome.config;
        minimal = self.nixosConfigurations.aurora-minimal.config;
        firstboot = imageProbe.config.systemd.services.aurora-firstboot;
        plasmaSetup = kde.systemd.services.plasma-setup;
        plasmaSetupPackage = self.nixosConfigurations.aurora-kde.pkgs.kdePackages.plasma-setup;
        gnomePkgs = self.nixosConfigurations.aurora-gnome.pkgs;
        installs = packages: lib.any (package: package.pname or "" == "plasma-setup") packages;
        patchedWith = name: package: lib.any (patch: lib.hasSuffix "-${name}" (toString patch)) (package.patches or [ ]);
        launchAuth = lib.splitString "\n" gnome.security.pam.services.gdm-launch-environment.text;
        autologinAuth = lib.filter (lib.hasPrefix "auth ")
          (lib.splitString "\n" kde.security.pam.services.plasmalogin-autologin.text);
        greeter = kde.systemd.services.plasmalogin;
        kdeWith = module: (self.nixosConfigurations.aurora-kde.extendModules { modules = [ module ]; }).config;
        # What the rekey writes into owner.nix once the password unlocks the disk.
        kdeRekeyed = kdeWith { aurora.firstboot.passwordHooks = false; };
        kdeGerman = kdeWith { services.xserver.xkb.layout = "de"; };
        kdeGermanFrenchConsole = kdeWith { services.xserver.xkb.layout = "de"; console.keyMap = "fr"; };
        kdeSshAtBoot = kdeWith { aurora.openssh.startAtBoot = true; };
        # Graphical first boot: each failed expectation is reported by name.
        desktopExpectations = {
          "desktop images boot with the Aurora splash" = kde.boot.plymouth.enable && gnome.boot.plymouth.enable
            && kde.boot.plymouth.theme == "aurora" && gnome.boot.plymouth.theme == "aurora"
            && lib.all (c: lib.any (p: (p.pname or "") == "plymouth-theme-aurora") c.boot.plymouth.themePackages) [ kde gnome ]
            && lib.all (c: lib.hasInfix "DeviceScale=1" c.boot.plymouth.extraConfig) [ kde gnome ];
          "every profile selects the patched Plymouth" = lib.all (c:
            c.boot.plymouth.package.drvPath == pkgs.plymouth.drvPath
            && patchedWith "0001-ply-terminal-Keep-terminal-input-nonblocking.patch" c.boot.plymouth.package
            && patchedWith "0001-Fix-splash-keyboard-lifetime.patch" c.boot.plymouth.package
            && c.boot.plymouth.package.scriptKeyboardLifetime >= 1
            && patchedWith "0002-drm-Reset-inherited-HDR-connector-state-before-SDR.patch" c.boot.plymouth.package
            && c.boot.plymouth.package.doCheck) [ kde gnome minimal ];
          "minimal images boot without a splash" = !minimal.boot.plymouth.enable;
          "the initrd asks for no TPM drivers, which the shared kernel lacks" = lib.all (c:
            !(lib.elem "tpm-tis" c.boot.initrd.availableKernelModules)
            && !(lib.elem "tpm-crb" c.boot.initrd.availableKernelModules)) [ kde gnome minimal ];
          "every image has an OpenSSH server that starts only on request" = lib.all (c:
            c.services.openssh.enable && !c.services.openssh.startWhenNeeded
            && c.systemd.services.sshd.wantedBy == [ ] && c.systemd.services.sshd-keygen.wantedBy == [ ]
            && lib.elem "sshd-keygen.service" c.systemd.services.sshd.wants
            && !(lib.elem 22 c.networking.firewall.allowedTCPPorts)) [ kde gnome minimal ];
          "aurora.openssh.startAtBoot starts the OpenSSH server at boot" =
            lib.elem "multi-user.target" kdeSshAtBoot.systemd.services.sshd.wantedBy
            && lib.elem "multi-user.target" kdeSshAtBoot.systemd.services.sshd-keygen.wantedBy;
          "desktop images start graphical.target" = kde.systemd.defaultUnit == "graphical.target"
            && gnome.systemd.defaultUnit == "graphical.target";
          "the splash quits only after first-boot setup" = !(lib.elem "plymouth-quit.service" firstboot.after)
            && lib.elem "aurora-firstboot.service" kde.systemd.services.plymouth-quit.after
            && lib.elem "aurora-firstboot.service" gnome.systemd.services.plymouth-quit.after;
          "first boot runs while pending, or for aurora.firstboot=text" =
            firstboot.unitConfig.ConditionPathExists == "|/var/lib/aurora/firstboot/pending"
            && firstboot.unitConfig.ConditionKernelCommandLine == "|aurora.firstboot=text";
          "first boot never takes tty1 from Plymouth" = firstboot.serviceConfig.StandardInput == "null"
            && !(firstboot.serviceConfig ? TTYPath) && !(firstboot.serviceConfig ? TTYVHangup);
          "images create the owner imperatively" = kde.users.mutableUsers && gnome.users.mutableUsers && minimal.users.mutableUsers;
          "Plasma Setup runs on KDE images only" = kde.aurora.plasmaSetup.enable
            && !gnome.aurora.plasmaSetup.enable && !minimal.aurora.plasmaSetup.enable;
          "Plasma Setup is enabled after the disk step" = lib.elem "multi-user.target" plasmaSetup.wantedBy
            && lib.elem "aurora-firstboot.service" plasmaSetup.after
            && plasmaSetup.unitConfig.ConditionPathExists == [ "!/var/lib/aurora/firstboot/pending" "!/var/lib/aurora/firstboot/complete" ];
          "Plasma Setup's unit, D-Bus helper, tmpfiles and polkit files are installed" = installs kde.systemd.packages
            && installs kde.services.dbus.packages && installs kde.systemd.tmpfiles.packages && installs kde.environment.systemPackages;
          "Plasma Setup is patched for NixOS paths" = patchedWith "plasma-setup-nixos-paths.patch" plasmaSetupPackage;
          "Plasma Setup's autostart entry is not executable" =
            kde.systemd.tmpfiles.settings.plasma-setup-xdg-autostart."/run/plasma-setup/.config/autostart/*.desktop".z.mode == "0640";
          "the setup user is a system user with its sysusers home" = kde.users.users.plasma-setup.isSystemUser
            && kde.users.users.plasma-setup.home == "/run/plasma-setup" && kde.users.groups ? plasma-setup;
          "KDE signs in with Plasma Login Manager, whose greeter runs on KWin Wayland, not SDDM" =
            kde.services.displayManager.plasma-login-manager.enable && !kde.services.displayManager.sddm.enable
            && !gnome.services.displayManager.plasma-login-manager.enable
            && !minimal.services.displayManager.plasma-login-manager.enable;
          "Plasma Login is the display-manager.service alias and the only KDE greeter unit" =
            lib.elem "display-manager.service" greeter.aliases && lib.elem "graphical.target" greeter.wantedBy
            && !(kde.systemd.services ? display-manager);
          "the KDE greeter waits for the disk step" = lib.elem "aurora-firstboot.service" greeter.after
            && greeter.unitConfig.ConditionPathExists == "!/var/lib/aurora/firstboot/pending";
          "Plasma Login may log the setup user in automatically: no UID floor" = autologinAuth != [ ]
            && !(lib.any (lib.hasInfix "pam_succeed_if.so") autologinAuth);
          "Plasma Login reads Plasma Setup's autologin from /etc/plasmalogin.conf.d" =
            kde.environment.etc ? "plasmalogin.conf.d/00-nixos-defaults.conf";
          "Plasma Setup's autologin session exists" = lib.elem "plasma" kde.services.displayManager.sessionData.sessionNames;
          "the Nix build users are not counted as accounts" = kde.security.loginDefs.settings.UID_MAX < kde.ids.uids.nixbld;
          "Plasma Login keeps the splash for the disk password, as GDM does" =
            lib.elem "plymouth-quit.service" greeter.conflicts && lib.elem "plymouth-quit.service" greeter.onFailure
            && kde.systemd.services.plymouth-quit.wantedBy == [ ]
            && lib.elem "plymouth-quit.service" gnome.systemd.services.display-manager.conflicts;
          "GNOME Initial Setup runs on GNOME images only" = gnome.aurora.gnomeInitialSetup.enable
            && gnome.services.gnome.gnome-initial-setup.enable
            && !kde.aurora.gnomeInitialSetup.enable && !minimal.aurora.gnomeInitialSetup.enable;
          "GDM finds GNOME Initial Setup's session in the system profile" =
            gnome.services.displayManager.generic.execCmd == "exec ${gnomePkgs.aurora-gdm}/bin/gdm"
            && patchedWith "gdm-initial-setup-session-path.patch" gnomePkgs.aurora-gdm
            && lib.any (package: package.pname or "" == "gnome-initial-setup") gnome.services.displayManager.gdm.extraPackages;
          "GNOME Initial Setup keeps its account and password pages" =
            lib.any (lib.hasInfix "aurora-gnome-initial-setup-vendor.conf") gnomePkgs.gnome-initial-setup.mesonFlags;
          "GDM runs the setup session as its gnome-initial-setup users" =
            lib.all (name: let user = gnome.users.users.${name} or { }; in
              user.isSystemUser or false && user.group or "" == "gnome-initial-setup"
              && user.home or "" == "/run/gdm/home/${name}")
              [ "gnome-initial-setup" "gnome-initial-setup-2" "gnome-initial-setup-5" ]
            && lib.length (lib.filter (lib.hasInfix "user ingroup gdm:gnome-initial-setup") launchAuth) == 3;
          "the setup session keeps gnome-session's template" =
            gnome.systemd.user.targets."gnome-session@gnome-initial-setup".overrideStrategy == "asDropin";
          "GDM's setup-done marker is cleared only before the display manager starts" =
            lib.elem "display-manager.service" gnome.systemd.services.aurora-gnome-initial-setup.wantedBy
            && lib.elem "display-manager.service" gnome.systemd.services.aurora-gnome-initial-setup.before
            && gnome.systemd.services.aurora-gnome-initial-setup.unitConfig.ConditionPathExists == "/run/gdm/gdm.ran-initial-setup";
          "GNOME declares its account setup to aurora-firstboot" =
            gnome.environment.etc."aurora/desktop-account-setup".text == "gnome-initial-setup\n"
            && !(kde.environment.etc ? "aurora/desktop-account-setup")
            && !(minimal.environment.etc ? "aurora/desktop-account-setup");
          "the first password sign-in hooks are declared until the rekey" =
            kde.security.pam.services.plasmalogin.rules.auth ? aurora-password-hook
            && kde.security.pam.services.plasmalogin-autologin.rules.auth ? aurora-password-gate
            && lib.hasInfix "aurora-password-hook" kde.security.pam.services.plasmalogin.text
            && gnome.security.pam.services.gdm-password.rules.auth ? aurora-password-hook
            && kde.environment.etc."aurora/password-hooks".text == "plasmalogin plasmalogin-autologin\n"
            && gnome.environment.etc."aurora/password-hooks".text == "gdm-password\n";
          "a rebuild after the rekey removes the hooks" =
            !(kdeRekeyed.security.pam.services.plasmalogin.rules.auth ? aurora-password-hook)
            && !(kdeRekeyed.security.pam.services.plasmalogin-autologin.rules.auth ? aurora-password-gate)
            && !(lib.hasInfix "aurora-password-hook" kdeRekeyed.security.pam.services.plasmalogin.text)
            && !(kdeRekeyed.environment.etc ? "aurora/password-hooks");
          "the console keymap follows the XKB layout unless set" = kde.console.keyMap == "us"
            && lib.hasSuffix "-xkb-console-keymap" (toString kdeGerman.console.keyMap)
            && kdeGermanFrenchConsole.console.keyMap == "fr"
            && lib.hasInfix "layout=de\n" kdeGerman.environment.etc."aurora/keyboard".text;
          "the initrd unlock prompt waits for the console keymap" = lib.elem "systemd-vconsole-setup.service"
            imageProbe.config.boot.initrd.systemd.services.aurora-initrd-root.after;
          "NetworkManager's dispatcher stays on the bus until NetworkManager stops" = lib.all (c: let
              dispatcher = c.systemd.services.NetworkManager-dispatcher;
            in lib.elem "NetworkManager.service" dispatcher.before
              && dispatcher.serviceConfig.ExecStart
                == [ "" "${c.networking.networkmanager.package}/libexec/nm-dispatcher --persist" ])
            [ kde gnome minimal ];
          "systemd-modules-load asks only for modules this kernel provides" = lib.all (c: let
              conf = lib.splitString "\n" c.environment.etc."modules-load.d/nixos.conf".source.text;
            in lib.elem "loop" conf && !(lib.elem "atkbd" conf) && !(lib.elem "cpufreq_schedutil" conf))
            [ kde gnome minimal ];
          # dbus-broker logs "Ignoring duplicate name" for each service file
          # it reads a second time (modules/dbus.nix).
          "each bus reads every D-Bus service directory once" = lib.all (c: let
              sw = toString c.system.path;
              linked = map toString (lib.concatMap (output: output.paths) c.system.path.chosenOutputs);
              dirs = c.environment.etc."dbus-1".source.busServiceDirectories or { system = [ ]; session = [ sw ]; };
              once = list: list == lib.unique list && !(lib.any (p: p != sw && lib.elem p linked) list);
            in once dirs.system && once dirs.session && lib.elem sw dirs.system && !(lib.elem sw dirs.session)
              && lib.any (line: lib.hasPrefix "XDG_DATA_DIRS " line && lib.hasInfix "/run/current-system/sw/share" line)
                (lib.splitString "\n" c.environment.etc."pam/environment".text))
            [ kde gnome minimal ];
        };
      in pkgs.runCommand "aurora-firstboot-image-evaluation" {
        rootUnit = let
          units = imageProbe.config.boot.initrd.systemd.units;
        in lib.concatMapStrings (name: units.${name}.text)
          (lib.filter (lib.hasPrefix "dev-disk-by\\x2duuid-") (lib.attrNames units));
        desktopFailures = lib.concatStringsSep "\n" (lib.attrNames (lib.filterAttrs (_: met: !met) desktopExpectations));
        stage2Preserved = if builtins.hasAttr "m1n1/boot.bin" imageProbe.config.boot.loader.grub.extraFiles
          || !(builtins.hasAttr "m1n1/boot.bin" (makeSystem "minimal").config.boot.loader.grub.extraFiles)
          || !(nixpkgs.lib.hasInfix "aurora-install-stage2" imageProbe.config.boot.loader.grub.extraInstallCommands)
          || imageProbe.config.system.autoUpgrade.enable
          then "0" else "1";
        units = builtins.toJSON {
          firstboot = imageProbe.config.systemd.services.aurora-firstboot.serviceConfig;
          initrd = imageProbe.config.boot.initrd.systemd.services.aurora-initrd-root.serviceConfig;
          kernelModules = imageProbe.config.boot.initrd.kernelModules;
          sysroot = imageProbe.config.boot.initrd.systemd.units."sysroot.mount".text;
          rootDevice = imageProbe.config.boot.initrd.systemd.units."dev-mapper-root.device".text;
          mounts = map (mount: { inherit (mount) what where; }) imageProbe.config.boot.initrd.systemd.mounts;
          layout = imageProbe.config.aurora.imageLayout;
        };
      } ''
        [[ "$stage2Preserved" == 1 ]] || { echo 'installed rebuilds must install Stage 2 through aurora-install-stage2 only, and never upgrade unattended' >&2; exit 1; }
        if [[ -n "$desktopFailures" ]]; then
          printf 'graphical first boot: %s\n' "$desktopFailures" >&2
          exit 1
        fi
        case "$units" in
          *'What=/dev/mapper/root'*) echo 'initrd sysroot must not wait for the mapper of a root that may stay plaintext' >&2; exit 1 ;;
        esac
        case "$rootUnit" in
          *'JobRunningTimeoutSec=infinity'*) ;;
          *) echo 'initrd root device must not time out during first-boot conversion' >&2; exit 1 ;;
        esac
        case "$units" in
          *'JobRunningTimeoutSec=infinity'*) ;;
          *) echo 'initrd root mapper must not time out during first-boot conversion' >&2; exit 1 ;;
        esac
        case "$units" in
          *'modprobe apple_wdt'*) ;;
          *) echo 'initrd must take over the watchdog before conversion' >&2; exit 1 ;;
        esac
        printf '%s\n' "$units" > $out
      '';
      profiles = pkgs.runCommand "aurora-profile-evaluation" {
        profiles = builtins.toJSON (nixpkgs.lib.mapAttrs (_: value: {
          kernel = value.config.boot.kernelPackages.kernel.version;
          desktop = value.config.aurora.desktop;
          system = value.config.nixpkgs.hostPlatform.system;
        }) self.nixosConfigurations);
      } ''printf '%s\n' "$profiles" > $out'';
      };
    };
}
