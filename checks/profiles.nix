{ pkgs, nixpkgs, self }:
let
  kde = self.nixosConfigurations.aurora-kde;
  gnome = self.nixosConfigurations.aurora-gnome;
  minimal = self.nixosConfigurations.aurora-minimal;
  withDiskSwap = (kde.extendModules {
    modules = [ { swapDevices = [{ device = "/dev/disk/by-label/swap"; }]; } ];
  }).config;
  withZramOverride = (kde.extendModules {
    modules = [ { zramSwap = { enable = false; memoryPercent = 60; }; } ];
  }).config;
  usesDesktopZram = profile:
    let
      inherit (profile.config.zramSwap) enable memoryMax memoryPercent;
    in enable && memoryPercent == 100 && memoryMax == 8 * 1024 * 1024 * 1024;
in
assert usesDesktopZram kde && usesDesktopZram gnome;
assert !minimal.config.zramSwap.enable;
assert !withDiskSwap.zramSwap.enable && (builtins.head withDiskSwap.swapDevices).device == "/dev/disk/by-label/swap";
assert !withZramOverride.zramSwap.enable && withZramOverride.zramSwap.memoryPercent == 60;
pkgs.runCommand "aurora-profile-evaluation" {
  profiles = builtins.toJSON (nixpkgs.lib.mapAttrs (_: value: {
    kernel = value.config.boot.kernelPackages.kernel.version;
    desktop = value.config.aurora.desktop;
    system = value.config.nixpkgs.hostPlatform.system;
  }) self.nixosConfigurations);
} ''printf '%s\n' "$profiles" > $out''
