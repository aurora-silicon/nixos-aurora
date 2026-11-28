{ pkgs, nixpkgs, self }:
let
  inherit (nixpkgs) lib;
  profiles = lib.attrValues self.nixosConfigurations;
  kdeWith = module: (self.nixosConfigurations.aurora-kde.extendModules { modules = [ module ]; }).config;
  optedOut = kdeWith { boot.kernelParams = [ "user4k=off" ]; };
  disabled = kdeWith { aurora.userpages.enable = false; };
  expectations = {
    # The kernel offers 4K userspace pages by default: no profile adds user4k=.
    "every profile ships the launcher and no user4k= argument" = lib.all (value:
      !(lib.any (lib.hasPrefix "user4k=") value.config.boot.kernelParams)
      && lib.elem value.pkgs.aurora-userpages value.config.environment.systemPackages) profiles;
    "an owner's user4k=off is the only user4k= argument" =
      lib.filter (lib.hasPrefix "user4k=") optedOut.boot.kernelParams == [ "user4k=off" ];
    "aurora.userpages.enable = false leaves out the launcher" =
      !(lib.elem pkgs.aurora-userpages disabled.environment.systemPackages);
    "the launcher builds from the kernel's own source" =
      pkgs.aurora-userpages.src.outPath == pkgs.linux-asahi.kernel.src.outPath;
  };
in pkgs.runCommand "aurora-userpages-evaluation" {
  failures = lib.concatStringsSep "\n" (lib.attrNames (lib.filterAttrs (_: met: !met) expectations));
} ''
  if [[ -n "$failures" ]]; then printf '%s\n' "$failures" >&2; exit 1; fi
  ${pkgs.aurora-userpages}/bin/userpages --help > /dev/null
  touch $out
''
