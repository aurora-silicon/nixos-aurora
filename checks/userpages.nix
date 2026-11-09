{ pkgs, nixpkgs, self }:
let
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
''
