{ lib, pkgs, ... }:
let
  pkg = pkgs.aurora-m5-platform-config;
in
{
  # Deep sleep on the MacBook Pro (M5 Pro, J714s), as aurora-m5-platform-config
  # sets it on Fedora and ALARM (m5-platform/README.md): suspend is deep sleep
  # only, the lid suspends on battery, on AC and docked, and a system-sleep hook
  # arms the PMU RTC safety alarm the T6050 sleep driver needs. The unit is
  # skipped (ConditionFirmware) and the hook returns at once on every other Mac.
  systemd.packages = [ pkg ];
  systemd.services.aurora-m5-sleep-policy.wantedBy = [ "sysinit.target" ];
  # NixOS's systemd-sleep runs the hooks in /etc/systemd/system-sleep.
  environment.etc."systemd/system-sleep/50-aurora-m5-rtc-safety".source =
    "${pkg}/lib/systemd/system-sleep/50-aurora-m5-rtc-safety";
  environment.etc."aurora-m5-sleep.conf".source = lib.mkDefault
    "${pkg}/share/aurora-m5-platform-config/aurora-m5-sleep.conf";
}
