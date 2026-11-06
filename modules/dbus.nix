{ config, lib, pkgs, ... }:
# NixOS gives both buses system-path as a service directory, then every entry
# of services.dbus.packages. A package that is also in
# environment.systemPackages is read twice, and dbus-broker logs "Ignoring
# duplicate name" for its second copy (NixOS/nixpkgs#303078). The session bus
# also reads system-path through XDG_DATA_DIRS. Leave out the service
# directories whose files the bus already reads; policy directories stay.
let
  cfg = config.services.dbus;
  systemPath = toString config.system.path;
  packages = lib.unique (map toString cfg.packages);
  linked = map toString (lib.concatMap (output: output.paths) config.system.path.chosenOutputs);
  inSystemPath = p: p != systemPath && lib.elem p linked;
  # pam_env gives every user manager, and so the session bus, XDG_DATA_DIRS
  # ending in /run/current-system/sw/share.
  sessionReadsProfile = config.security.pam.services.systemd-user.setEnvironment
    && lib.elem "/run/current-system/sw" config.environment.profiles
    && lib.elem "/share" (config.environment.profileRelativeSessionVariables.XDG_DATA_DIRS or [ ]);
  busServiceDirectories = {
    system = lib.filter (p: !inSystemPath p) packages;
    session = lib.filter (p: !inSystemPath p && !(sessionReadsProfile && p == systemPath)) packages;
  };
  # The arguments nixos/modules/services/system/dbus.nix gives makeDBusConf.
  conf = pkgs.makeDBusConf.override {
    inherit (cfg) apparmor;
    dbus = cfg.dbusPackage;
    suidHelper = "${config.security.wrapperDir}/dbus-daemon-launch-helper";
    serviceDirectories = packages;
  };
  drop = subdir: kept: lib.concatMapStrings (p: " --replace-fail "
    + lib.escapeShellArg "<servicedir>${p}/share/dbus-1/${subdir}</servicedir>" + " ''")
    (lib.subtractLists kept packages);
in {
  config = lib.mkIf cfg.enable {
    environment.etc."dbus-1".source = lib.mkForce (pkgs.runCommandLocal "dbus-1" {
      passthru = { inherit busServiceDirectories; };
    } ''
      cp -r --no-preserve=mode ${conf} $out
      substituteInPlace $out/system.conf${drop "system-services" busServiceDirectories.system}
      substituteInPlace $out/session.conf${drop "services" busServiceDirectories.session}
    '');
  };
}
