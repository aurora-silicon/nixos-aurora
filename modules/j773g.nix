{ config, lib, ... }:

{
  fileSystems."/boot/efi" = {
    device = lib.mkOverride 40 "/dev/disk/by-label/AURORA_EFI";
    options = lib.mkOverride 40 [ "nofail" "x-systemd.device-timeout=5s" ];
  };

  boot.initrd.availableKernelModules = lib.mkForce [ ];
  boot.initrd.kernelModules = lib.mkForce [ ];
  # The binary package has no source tree from which to build cpupower. The
  # Apple cpufreq driver remains active with its firmware-selected policy.
  powerManagement.cpuFreqGovernor = lib.mkForce null;
  boot.kernelParams = [
    "user4k=on"
    "console=tty0"
    "earlycon"
    "panic=30"
    "pd_ignore_unused"
    "clk_ignore_unused"
    "nvme_apple.flush_interval=0"
    "root=UUID=${config.aurora.imageLayout.rootUUID}"
    "rootflags=subvol=root"
    "m4run=j773g-nixos"
    "ctxr_exec_enforce=0"
    "sn201202x.j773g_no_usb4=1"
    "sn201202x.j773g_no_tbt3=1"
  ];

  # Suspend/resume is not yet qualified on J773g. Keep an unattended test
  # image reachable and make all sleep entry points fail closed.
  services.logind.settings.Login = {
    IdleAction = "ignore";
    HandleSuspendKey = "ignore";
    HandleHibernateKey = "ignore";
    HandleLidSwitch = "ignore";
  };
  systemd.targets.sleep.enable = false;
  systemd.targets.suspend.enable = false;
  systemd.targets.hibernate.enable = false;
  systemd.targets.hybrid-sleep.enable = false;

  # PowerDevil reads these defaults for newly-created Plasma users.
  environment.etc."xdg/powerdevilprofilesrc".text = ''
    [AC][SuspendSession]
    idleTime=0
    suspendType=0
    [Battery][SuspendSession]
    idleTime=0
    suspendType=0
    [LowBattery][SuspendSession]
    idleTime=0
    suspendType=0
  '';
}
