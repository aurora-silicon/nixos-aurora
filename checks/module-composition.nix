{ pkgs, nixpkgs, makeSystem }:
let
  inherit (nixpkgs) lib;
  marker = pkgs.writeText "aurora-grub-extra-file" "host-owned GRUB file\n";
  installed = (makeSystem "minimal").extendModules {
    modules = [ {
      system.stateVersion = "25.11";
      boot.loader.grub.extraFiles."host/marker" = marker;
    } ];
  };
  disabled = installed.extendModules {
    modules = [ { aurora.stage2.enable = false; } ];
  };
  customPortal = installed.extendModules {
    modules = [ { xdg.portal.config.common.default = [ "host-portal" ]; } ];
  };
  preservesHostFile = config:
    config.boot.loader.grub.extraFiles."host/marker" == marker
    && !(config.boot.loader.grub.extraFiles ? "m1n1/boot.bin");
in
assert lib.assertMsg (installed.config.system.stateVersion == "25.11")
  "Aurora must preserve the host's initial stateVersion";
assert lib.assertMsg (preservesHostFile installed.config && preservesHostFile disabled.config)
  "Aurora must preserve host GRUB files and suppress the unchecked Stage 2 copy";
assert lib.assertMsg
  (installed.config.xdg.portal.config.common.default == "gtk"
    && customPortal.config.xdg.portal.config.common.default == "host-portal")
  "The minimal portal backend must be selected explicitly and remain overridable";
assert lib.assertMsg
  (lib.hasInfix "aurora-install-stage2" installed.config.boot.loader.grub.extraInstallCommands
    && !(lib.hasInfix "aurora-install-stage2" disabled.config.boot.loader.grub.extraInstallCommands))
  "Disabling Aurora Stage 2 updates must leave the ESP Stage 2 unchanged";
pkgs.runCommand "aurora-module-composition" { } "touch $out"
