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
# * A serial console does not force Plymouth's text view (fedora-aurora #155).
#   Without console=, the kernel also takes the device tree's stdout-path as a
#   console (the Neo's DockChannel UART), and Plymouth then shows its details
#   view on every display, the disk password prompt included. The kernel keeps
#   the serial console.
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
        # appledrm waits for every DCP; an external one binds only after its
        # Type-C PHY, whose retimer or PD controller sits on an I2C bus.
        *Capple,*atcphy*|*Capple,*-i2cC*|*Capple,i2c) ;;
        *) continue ;;
      esac
      devices+=("$(${readlink} -f "$dev")")
      for link in "$dev"/supplier:*; do
        [ -e "$link/supplier" ] && devices+=("$(${readlink} -f "$link/supplier")")
      done
    done
    [ ''${#devices[@]} -gt 0 ] || exit 0
    # Queue them ahead of the coldplug, then the DRM cards that exist
    # already, without waiting: the display processors take a second or
    # more to start and the root file system does not need them. Plymouth
    # adds appledrm's card from its udev add event.
    ${udevadm} trigger --action=add "''${devices[@]}"
    ${udevadm} trigger --action=add --subsystem-match=drm
  '';
  # Before the pivot: wait, briefly, for appledrm's DRM card and for udev to
  # initialize it, so Plymouth opens it (DRM master) while the initrd udevd
  # runs. Pivoting first lets an external display's hotplug make the fbdev
  # emulation, with no master to defer to, blank the panel before Plymouth
  # returns. 2 s at most; 1 s if no driver is bound to the display subsystem.
  kmsHandover = pkgs.writeShellScript "aurora-kms-handover" ''
    dev=/sys/bus/platform/devices/display-subsystem
    [ -e "$dev" ] || exit 0
    for ((tries = 0; tries < 40; tries++)); do
      for card in "$dev"/drm/card*; do
        [ -e "$card" ] || continue
        ${udevadm} wait --timeout=1 "/dev/dri/''${card##*/}" 2>/dev/null
        exit 0
      done
      [ -e "$dev/driver" ] || [ "$tries" -lt 20 ] || exit 0
      ${pkgs.coreutils}/bin/sleep 0.05
    done
  '';
in {
  # Desktop images boot to a splash. The Aurora theme draws the logo aura
  # shows, at the same size and place, with the spinner below it and
  # boot.plymouth.logo (the NixOS logo) at the bottom, so the logo stays
  # still from power-on to the greeter. Plymouth runs in the systemd initrd.
  boot.plymouth.enable = lib.mkDefault (config.aurora.desktop != "minimal");
  boot.plymouth.package = lib.mkDefault pkgs.plymouth;
  boot.plymouth.themePackages = [ pkgs.plymouth-theme-aurora ];
  boot.plymouth.theme = lib.mkDefault "aurora";
  # The theme draws in device pixels, so the logo matches aura's to the
  # pixel; Plymouth's own 2x scale on Retina panels would double it.
  boot.plymouth.extraConfig = lib.mkIf (config.boot.plymouth.theme == "aurora") "DeviceScale=1";
  # Each boot supplies the live DT geometry, including image builds and
  # rebuilds done on another machine. Keep the store and /etc immutable.
  boot.initrd.systemd.services.plymouth-start.preStart = lib.mkIf
    (config.boot.plymouth.enable && config.boot.plymouth.theme == "aurora") (lib.mkAfter ''
      PATH=${lib.makeBinPath [ pkgs.coreutils ]} ${pkgs.runtimeShell} \
        ${pkgs.plymouth-theme-aurora}/libexec/aurora-plymouth \
        ${pkgs.plymouth-theme-aurora}/share/plymouth/themes/aurora
    '');
  systemd.services.plymouth-start.preStart = lib.mkIf
    (config.boot.plymouth.enable && config.boot.plymouth.theme == "aurora") ''
      PATH=${lib.makeBinPath [ pkgs.coreutils ]} ${pkgs.runtimeShell} \
        ${pkgs.plymouth-theme-aurora}/libexec/aurora-plymouth \
        ${pkgs.plymouth-theme-aurora}/share/plymouth/themes/aurora
    '';

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

  boot.kernelParams = lib.mkIf config.boot.plymouth.enable [ "plymouth.ignore-serial-consoles" ];

  # The external DCPs' Type-C chain comes up with the display: appledrm
  # registers only once every DCP has bound.
  boot.initrd.availableKernelModules = [ "appledrm" "mux-apple-display-crossbar"
    "i2c-pasemi-platform" "phy-apple-atc" "phy-ti-cd2e22" "tps6598x" ];
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
  boot.initrd.systemd.services.aurora-kms-handover = lib.mkIf config.boot.plymouth.enable {
    description = "Hand the splash to the Apple display driver before the pivot";
    unitConfig.DefaultDependencies = false;
    wantedBy = [ "initrd.target" ];
    after = [ "initrd-root-fs.target" "systemd-udevd.service" "plymouth-start.service" "aurora-early-kms.service" ];
    before = [ "initrd-cleanup.service" "initrd-switch-root.target" ];
    serviceConfig.Type = "oneshot";
    serviceConfig.ExecStart = kmsHandover;
  };
  boot.initrd.systemd.storePaths = lib.mkIf config.boot.plymouth.enable (
    [ earlyKms kmsHandover "${pkgs.coreutils}/bin/sleep" ] ++ lib.optionals (config.boot.plymouth.theme == "aurora") [
      # The initrd copier does not follow store references inside shell scripts.
      "${pkgs.plymouth-theme-aurora}/libexec/aurora-plymouth"
      "${pkgs.plymouth-theme-aurora}/share/plymouth/themes/aurora"
    ]
  );
}
