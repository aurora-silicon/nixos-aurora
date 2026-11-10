{ pkgs, nixpkgs, self }:
pkgs.runCommand "aurora-profile-evaluation" {
  profiles = builtins.toJSON (nixpkgs.lib.mapAttrs (_: value: {
    kernel = value.config.boot.kernelPackages.kernel.version;
    desktop = value.config.aurora.desktop;
    system = value.config.nixpkgs.hostPlatform.system;
  }) self.nixosConfigurations);
} ''printf '%s\n' "$profiles" > $out''
