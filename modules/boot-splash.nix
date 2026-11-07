# The boot logo stays on screen from aura through the splash to the login
# screen, as on Fedora Aurora (fedora-aurora #148, #149, #151):
#
# * GRUB leaves the screen alone: no gfxterm (a font or splash image switches
#   GRUB to gfxterm, which sets a GOP mode and clears the logo), and the menu
#   stays hidden unless Esc is pressed during the one-second timeout.
# * The initrd carries the Apple display driver and coldplugs the display,
#   its DCPs and their device-link suppliers before the other devices, so
#   Plymouth starts on appledrm instead of waiting for the real root.
# * Plymouth starts once udevd runs instead of after the whole coldplug has
#   been queued (overlay.nix carries the unit patch).
#
# Every setting is a default: a system configuration's own choice wins.
{ config, lib, pkgs, ... }:
let
  udevadm = "${config.boot.initrd.systemd.package}/bin/udevadm";
  readlink = "${pkgs.coreutils}/bin/readlink";
  earlyKms = pkgs.writeShellScript "aurora-early-kms" ''
    set -u
    devices=()
    for dev in /sys/bus/platform/devices/*; do
      [ -r "$dev/modalias" ] || continue
      read -r alias < "$dev/modalias" || continue
      case "$alias" in
        *Capple,display-subsystem*|*Capple,dcp*) ;;
        *) continue ;;
      esac
      devices+=("$(${readlink} -f "$dev")")
      for link in "$dev"/supplier:*; do
        [ -e "$link/supplier" ] && devices+=("$(${readlink} -f "$link/supplier")")
      done
    done
    [ ''${#devices[@]} -gt 0 ] || exit 0
    ${udevadm} trigger --action=add --settle "''${devices[@]}"
    ${udevadm} settle --timeout=5
    ${udevadm} trigger --action=add --subsystem-match=drm --settle
  '';
in {
  # The spinner needs no ACPI BGRT logo and runs in the systemd initrd.
  boot.plymouth.enable = lib.mkDefault (config.aurora.desktop != "minimal");
  boot.plymouth.package = lib.mkDefault pkgs.plymouth;
  boot.plymouth.theme = lib.mkDefault "spinner";

  # Plasma Login, like GDM, owns the splash until its greeter starts. Its
  # display-manager.service is an alias, not a second service definition.
  systemd.services.plasmalogin = lib.mkIf (config.services.displayManager.plasma-login-manager.enable && config.boot.plymouth.enable) {
    conflicts = [ "plymouth-quit.service" ];
    after = [ "plymouth-start.service" ];
    onFailure = [ "plymouth-quit.service" ];
    serviceConfig.ExecStartPre = [
      "-${pkgs.coreutils}/bin/timeout --kill-after=2 20 ${lib.getExe' config.boot.plymouth.package "plymouth"} quit"
    ];
  };
  # Starting this unit during a switch would stop the display manager.
  systemd.services.plymouth-quit = lib.mkIf (config.services.displayManager.plasma-login-manager.enable && config.boot.plymouth.enable) {
    wantedBy = lib.mkForce [ ];
  };

  boot.loader.grub.font = lib.mkDefault null;
  # grub.nix sets its NixOS wallpaper with mkDefault, so a plain mkDefault
  # null would conflict with it; one step stronger still loses to a
  # configuration's own setting.
  boot.loader.grub.splashImage = lib.mkOverride 999 null;
  boot.loader.grub.timeoutStyle = lib.mkDefault "hidden";
  boot.loader.timeout = lib.mkDefault 1;

  boot.initrd.availableKernelModules = [ "appledrm" "mux-apple-display-crossbar" ];
  boot.initrd.systemd.services.aurora-early-kms = lib.mkIf config.boot.plymouth.enable {
    description = "Coldplug the Apple display before the other devices";
    unitConfig.DefaultDependencies = false;
    wantedBy = [ "sysinit.target" ];
    after = [ "systemd-udevd.service" ];
    wants = [ "systemd-udevd.service" ];
    before = [ "systemd-udev-trigger.service" "plymouth-start.service" ];
    serviceConfig.Type = "oneshot";
    serviceConfig.ExecStart = earlyKms;
  };
  boot.initrd.systemd.storePaths = lib.mkIf config.boot.plymouth.enable [ earlyKms ];
}
