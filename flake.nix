{
  description = "Aurora NixOS for Apple Silicon";
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/e7439b6b14ad3cc35d05608ebca9bce01a25f5f8";
    apple-silicon.url = "github:nix-community/nixos-apple-silicon/12cd234285d3037cedfab979aa70b75284a59afc";
    apple-silicon.inputs.nixpkgs.follows = "nixpkgs";
  };
  outputs = { self, nixpkgs, apple-silicon, ... }:
    let
      system = "aarch64-linux";
      overlays = [ apple-silicon.overlays.default self.overlays.default ];
      pkgs = import nixpkgs { inherit system overlays; };
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
        firstboot = pkgs.aurora-firstboot;
        sep = pkgs.aurora-sep;
        libfprint = pkgs.libfprint;
        avd-fw = pkgs.aurora-avd-firmware;
        omarchy-ane-tools = pkgs.omarchy-ane-tools;
        mil-hwx-compiler = pkgs.mil-hwx-compiler;
        upower = pkgs.upower;
        bindgen = pkgs.aurora-bindgen;
        aura = pkgs.m1n1;
        uboot = pkgs.uboot-asahi;
        kernel = pkgs.linux-asahi.kernel;
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
        audio = pkgs.asahi-audio;
        ucm = pkgs.alsa-ucm-conf-asahi;
        fex-mesa = pkgs.aurora-fex-mesa;
        flatpak-gl = pkgs.aurora-flatpak-gl;
        speakerguardd = pkgs.speakerguardd;
        mutter = pkgs.mutter;
        speakersafetyd = pkgs.speakersafetyd;
        bankstown = pkgs.bankstown-lv2;
        neo-platform = pkgs.aurora-neo-platform-config;
        aurora-bless = pkgs.aurora-bless;
      };
      # The payload runs in an ARM machine's x86 guest, and is built on x86.
      packages.x86_64-linux.fex-mesa = pkgs.aurora-fex-mesa;
      checks.${system} = {
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
              "early display audio carries the sequencer" = lib.elem "snd-seq" config.boot.initrd.availableKernelModules;
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
        autologinAuth = lib.splitString "\n" kde.security.pam.services.sddm-autologin.text;
        lineOf = match: lib.lists.findFirstIndex match null autologinAuth;
        setupAutologin = lineOf (line: lib.hasPrefix "auth sufficient " line && lib.hasInfix "pam_succeed_if.so" line
          && lib.hasInfix "user = plasma-setup" line);
        uidAutologin = lineOf (line: lib.hasInfix "pam_succeed_if.so" line && lib.hasInfix "uid >= 1000" line);
        kdeWith = module: (self.nixosConfigurations.aurora-kde.extendModules { modules = [ module ]; }).config;
        # What the rekey writes into owner.nix once the password unlocks the disk.
        kdeRekeyed = kdeWith { aurora.firstboot.passwordHooks = false; };
        kdeGerman = kdeWith { services.xserver.xkb.layout = "de"; };
        kdeGermanFrenchConsole = kdeWith { services.xserver.xkb.layout = "de"; console.keyMap = "fr"; };
        kdeSshAtBoot = kdeWith { aurora.openssh.startAtBoot = true; };
        # Graphical first boot: each failed expectation is reported by name.
        desktopExpectations = {
          "desktop images boot with the spinner splash" = kde.boot.plymouth.enable && gnome.boot.plymouth.enable
            && kde.boot.plymouth.theme == "spinner" && gnome.boot.plymouth.theme == "spinner";
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
          "the setup user is a system user with its sysusers home" = kde.users.users.plasma-setup.isSystemUser
            && kde.users.users.plasma-setup.home == "/run/plasma-setup" && kde.users.groups ? plasma-setup;
          "SDDM may log the setup user in automatically, and only it below UID 1000" = setupAutologin != null
            && uidAutologin != null && setupAutologin < uidAutologin;
          "SDDM reads Plasma Setup's autologin from /etc/sddm.conf.d" = kde.environment.etc ? "sddm.conf.d/00-nixos.conf";
          "Plasma Setup's autologin session exists" = lib.elem "plasma" kde.services.displayManager.sessionData.sessionNames;
          "the Nix build users are not counted as accounts" = kde.security.loginDefs.settings.UID_MAX < kde.ids.uids.nixbld;
          "SDDM keeps the splash for the disk password, as GDM does" =
            lib.elem "plymouth-quit.service" kde.systemd.services.display-manager.conflicts
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
            kde.security.pam.services.sddm.rules.auth ? aurora-password-hook
            && kde.security.pam.services.sddm-autologin.rules.auth ? aurora-password-gate
            && gnome.security.pam.services.gdm-password.rules.auth ? aurora-password-hook
            && kde.environment.etc ? "aurora/password-hooks";
          "a rebuild after the rekey removes the hooks" =
            !(kdeRekeyed.security.pam.services.sddm.rules.auth ? aurora-password-hook)
            && !(kdeRekeyed.security.pam.services.sddm-autologin.rules.auth ? aurora-password-gate)
            && !(lib.hasInfix "aurora-password-hook" kdeRekeyed.security.pam.services.sddm.text)
            && !(kdeRekeyed.environment.etc ? "aurora/password-hooks");
          "the console keymap follows the XKB layout unless set" = kde.console.keyMap == "us"
            && lib.hasSuffix "-xkb-console-keymap" (toString kdeGerman.console.keyMap)
            && kdeGermanFrenchConsole.console.keyMap == "fr"
            && lib.hasInfix "layout=de\n" kdeGerman.environment.etc."aurora/keyboard".text;
          "the initrd unlock prompt waits for the console keymap" = lib.elem "systemd-vconsole-setup.service"
            imageProbe.config.boot.initrd.systemd.services.aurora-initrd-root.after;
        };
      in pkgs.runCommand "aurora-firstboot-image-evaluation" {
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
          *'What=/dev/mapper/root'*) ;;
          *) echo 'initrd sysroot must use the encrypted root mapper from boot start' >&2; exit 1 ;;
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
