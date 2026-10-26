{ pkgs, ... }:
{
  # Explicit service loading waits for /var and per-machine firmware. This only
  # suppresses early alias loading; the boot timer enables SEP on the real root.
  boot.blacklistedKernelModules = [ "apple_sep" ];
  environment.systemPackages = [ pkgs.aurora-sep pkgs.libfprint ];
  services.fprintd.enable = true;
  systemd.timers.aurora-sep = {
    description = "Initialize Aurora SEP after persistent storage is available";
    wantedBy = [ "timers.target" ];
    timerConfig.OnBootSec = "1";
    timerConfig.Unit = "aurora-sep.service";
  };
  systemd.services.aurora-sep = {
    description = "Aurora SEP trusted keys and biometric services";
    after = [ "local-fs.target" "aurora-vendor-firmware.service" ];
    wants = [ "aurora-vendor-firmware.service" "aurora-sep-ready.service" ];
    unitConfig = {
      RequiresMountsFor = "/var/lib";
      ConditionPathExists = "/dev/disk/by-partlabel/iBootSystemContainer";
    };
    path = [ pkgs.kmod pkgs.gnugrep ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecCondition = "${pkgs.runtimeShell} -c 'modinfo -F filename apple_sep 2>/dev/null | grep -Eq \"[.]ko([.](gz|xz|zst))?$\"'";
      ExecStartPre = "${pkgs.aurora-sep}/libexec/aurora/prepare-sep-calibration";
      ExecStart = "${pkgs.aurora-sep}/libexec/aurora-sep-load";
      StateDirectory = "aurora-sep";
      StateDirectoryMode = "0700";
      TimeoutStartSec = 180;
    };
  };
  systemd.services.aurora-sep-ready = {
    description = "Restore fingerprint reader state";
    requires = [ "aurora-sep.service" ];
    after = [ "aurora-sep.service" ];
    before = [ "fprintd.service" ];
    unitConfig.ConditionPathExists = "/dev/sep-bio";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecCondition = [
        "${pkgs.aurora-sep}/libexec/aurora/sensor-present"
        "${pkgs.aurora-sep}/libexec/aurora/calibration-ready"
      ];
      ExecStart = "${pkgs.aurora-sep}/libexec/aurora-sep-ready";
      TimeoutStartSec = 60;
    };
  };
  systemd.services.fprintd = {
    requires = [ "aurora-sep.service" ];
    after = [ "aurora-sep.service" "aurora-sep-ready.service" ];
    unitConfig.ConditionPathExists = "/dev/sep-bio";
    serviceConfig.ExecCondition = [
      "${pkgs.aurora-sep}/libexec/aurora/sensor-present"
      "${pkgs.aurora-sep}/libexec/aurora/calibration-ready"
    ];
    serviceConfig.DeviceAllow = [ "/dev/sep-bio rw" "char-input r" ];
  };
}
