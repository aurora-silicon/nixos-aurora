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
        modules = [ { aurora.imageLayout = {
          rootUUID = "eb688499-cc41-4c4c-b00b-dbf33e05427c";
          bootUUID = "3429647d-29a2-411c-8924-2545fda1ec34";
          efiUUID = "1E08-14ED";
        }; } ];
      };
    in {
      overlays.default = import ./overlay.nix;
      nixosModules.default = import ./modules/aurora.nix;
      nixosConfigurations = {
        aurora-kde = makeSystem "kde";
        aurora-gnome = makeSystem "gnome";
        aurora-minimal = makeSystem "minimal";
      };
      packages.${system} = {
        firstboot = pkgs.aurora-firstboot;
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
      firstboot-image = pkgs.runCommand "aurora-firstboot-image-evaluation" {
        units = builtins.toJSON {
          firstboot = imageProbe.config.systemd.services.aurora-firstboot.serviceConfig;
          initrd = imageProbe.config.boot.initrd.systemd.services.aurora-initrd-root.serviceConfig;
          sysroot = imageProbe.config.boot.initrd.systemd.units."sysroot.mount".text;
          mounts = map (mount: { inherit (mount) what where; }) imageProbe.config.boot.initrd.systemd.mounts;
          layout = imageProbe.config.aurora.imageLayout;
        };
      } ''printf '%s\n' "$units" > $out'';
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
