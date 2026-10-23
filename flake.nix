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
      firstboot-image = pkgs.runCommand "aurora-firstboot-image-evaluation" {
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
