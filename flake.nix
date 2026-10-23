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
        upower = pkgs.upower;
        bindgen = pkgs.aurora-bindgen;
        aura = pkgs.m1n1;
        uboot = pkgs.uboot-asahi;
        kernel = pkgs.linux-asahi.kernel;
        mesa = pkgs.mesa;
        speakerguardd = pkgs.speakerguardd;
        bankstown = pkgs.bankstown-lv2;
        neo-platform = pkgs.aurora-neo-platform-config;
        aurora-bless = pkgs.aurora-bless;
      };
      checks.${system} = {
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
        # Graphical first boot: each failed expectation is reported by name.
        desktopExpectations = {
          "desktop images boot with the spinner splash" = kde.boot.plymouth.enable && gnome.boot.plymouth.enable
            && kde.boot.plymouth.theme == "spinner" && gnome.boot.plymouth.theme == "spinner";
          "minimal images boot without a splash" = !minimal.boot.plymouth.enable;
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
          "GDM runs the setup session as its gnome-initial-setup user" =
            gnome.users.users.gnome-initial-setup.isSystemUser
            && gnome.users.users.gnome-initial-setup.group == "gnome-initial-setup"
            && gnome.users.users.gnome-initial-setup.home == "/run/gdm/home/gnome-initial-setup"
            && lib.length (lib.filter (lib.hasInfix "user ingroup gdm:gnome-initial-setup") launchAuth) == 3;
          "GDM's setup-done marker is cleared only before the display manager starts" =
            lib.elem "display-manager.service" gnome.systemd.services.aurora-gnome-initial-setup.wantedBy
            && lib.elem "display-manager.service" gnome.systemd.services.aurora-gnome-initial-setup.before
            && gnome.systemd.services.aurora-gnome-initial-setup.unitConfig.ConditionPathExists == "/run/gdm/gdm.ran-initial-setup";
          "GNOME declares its account setup to aurora-firstboot" =
            gnome.environment.etc."aurora/desktop-account-setup".text == "gnome-initial-setup\n"
            && !(kde.environment.etc ? "aurora/desktop-account-setup")
            && !(minimal.environment.etc ? "aurora/desktop-account-setup");
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
