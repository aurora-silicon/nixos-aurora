{ pkgs, nixpkgs, self }:
let
  inherit (nixpkgs) lib;
  profiles = lib.attrValues self.nixosConfigurations;
  valid = lib.versionAtLeast pkgs.bluez.version "5.87"
    && lib.any (patch: lib.hasSuffix "docker-query-forwarding-policy.patch" (toString patch))
      (pkgs.docker.moby.patches or [ ])
    && pkgs.docker.moby.doCheck
    && lib.all (profile: let unit = profile.config.systemd.units."var-swap-swapfile2.swap"; in
      unit.overrideStrategy == "asDropin"
      && lib.hasInfix "After=var-swap-swapfile.swap" unit.text) profiles;
in assert lib.assertMsg valid "Aurora clean-boot packaging parity failed";
  pkgs.runCommand "aurora-clean-boot-defaults" { } "touch $out"
