{
  description = "Aurora NixOS for Apple Silicon";
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/1d060086d60cb76a40cf37109f979d88a5bd6396";
    apple-silicon.url = "github:nix-community/nixos-apple-silicon/12cd234285d3037cedfab979aa70b75284a59afc";
    apple-silicon.inputs.nixpkgs.follows = "nixpkgs";
    nuschtos-search = {
      url = "github:NuschtOS/search/cbdbeef58566d5107808b467832c2203387c2dec";
      inputs.nixpkgs.follows = "nixpkgs";
    };
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
        modules = [ apple-silicon.nixosModules.default self.nixosModules.default self.nixosModules.installed
          { nixpkgs.overlays = overlays; aurora.desktop = desktop; }
          ./modules/image.nix ];
      };
    in {
      overlays.default = import ./overlay.nix;
      nixosModules.image = ./modules/image.nix;
      nixosModules.default = ./modules/aurora.nix;
      # An installed system: the native installer provisioned Stage 1, which
      # rebuilds never touch; every bootloader install refreshes the ESP
      # Stage 2 as update-m1n1 does on ALARM and Fedora (modules/installed.nix).
      nixosModules.installed = ./modules/installed.nix;
      nixosConfigurations = {
        aurora-kde = makeSystem "kde";
        aurora-gnome = makeSystem "gnome";
        aurora-minimal = makeSystem "minimal";
      };
      packages.${system} = {
        inherit (pkgs)
          plymouth docker libfprint fprintd omarchy-ane-tools mil-hwx-compiler upower
          fex steam mesa speakerguardd mutter speakersafetyd aurora-bless
          plymouth-theme-aurora omdrop-awdl speakerguardd-v2 iio-sensor-proxy
          gnome-settings-daemon;
        logos = pkgs.aurora-logos;
        firstboot = pkgs.aurora-firstboot;
        power-budget = pkgs.aurora-power-budget;
        sep = pkgs.aurora-sep;
        avd-fw = pkgs.aurora-avd-firmware;
        speaker-upgrade = pkgs.aurora-speaker-upgrade;
        libva-v4l2-request-avd = pkgs.libvaV4l2RequestAvd;
        bindgen = pkgs.aurora-bindgen;
        aura = pkgs.m1n1;
        uboot = pkgs.uboot-asahi;
        kernel = pkgs.linux-asahi.kernel;
        userpages = pkgs.aurora-userpages;
        proton = pkgs.aurora-proton;
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
        kwin = pkgs.kdePackages.kwin;
        bankstown = pkgs.bankstown-lv2;
        neo-platform = pkgs.aurora-neo-platform-config;
        camera-denoise = pkgs.aurora-camera-denoise;
        kbd-light = pkgs.aurora-kbd-light;
        panel-nits = pkgs.aurora-panel-nits;
        nvram = pkgs.aurora-nvram;
        btsync = pkgs.aurora-btsync;
        fido = pkgs.aurora-fido;
        sep-sk = pkgs.aurora-sep-sk;
        xart = pkgs.aurora-xart;
        sep-luks = pkgs.aurora-sep-luks;
        firefox = pkgs.firefox-unwrapped;
      };
      # The payload runs in an ARM machine's x86 guest, and is built on x86.
      packages.x86_64-linux.fex-mesa = pkgs.aurora-fex-mesa;
      checks.${system} = import ./checks {
        inherit self nixpkgs pkgs system overlays makeSystem;
      };
    };
}
