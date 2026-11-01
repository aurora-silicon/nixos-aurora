{ config, lib, pkgs, ... }:
{
  environment.systemPackages = [ pkgs.aurora-logos ];
  # Plasma reads this native XDG configuration; the immutable package supplies
  # the logo. NixOS continues generating its own distribution identity.
  environment.etc = lib.mkIf (config.aurora.desktop == "kde") {
    "xdg/kcm-about-distrorc".text = ''
      [General]
      Name=Aurora NixOS
      LogoPath=${pkgs.aurora-logos}/share/pixmaps/system-logo-white.png
      Website=https://aurorasilicon.org
    '';
  };
}
