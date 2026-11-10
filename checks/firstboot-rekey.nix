# A normal virtual machine exercises the packaged PAM/rekey entry points.
# Its LUKS volume is a newly created regular file, never a host block device.
{ pkgs, imageProbe, self }:
let
  greeter = self.nixosConfigurations.aurora-kde.config.security.pam.services;
  rule = value: builtins.removeAttrs value [ "name" ];
in pkgs.testers.runNixOSTest {
  name = "aurora-firstboot-rekey";
  requiredFeatures.kvm = false;
  nodes.machine = _: {
    virtualisation.memorySize = 2048;
    environment.systemPackages = [ pkgs.cryptsetup pkgs.pamtester pkgs.pam ];
    users.users.owner = {
      isNormalUser = true;
      initialPassword = "fixture-owner-password";
    };
    users.users.setup = { isSystemUser = true; group = "setup"; };
    users.groups.setup = {};
    security.pam.services.aurora-fixture.rules.auth.aurora-password-hook =
      rule greeter.plasmalogin.rules.auth.aurora-password-hook;
    security.pam.services.aurora-gate = {
      unixAuth = false;
      rules.auth = {
        aurora-password-gate = rule greeter.plasmalogin-autologin.rules.auth.aurora-password-gate;
        fixture-allow = {
          order = 1000;
          control = "sufficient";
          modulePath = "${pkgs.pam}/lib/security/pam_permit.so";
        };
      };
    };
    environment.etc."aurora/password-hooks".text = "aurora-fixture aurora-gate\n";
    environment.etc."aurora/keyboard".text = "layout=us\nvariant=\n";
    # Keep the production condition, command and service type. The barrier
    # lets the test inspect the PAM handoff's permissions before consuming it.
    systemd.services.aurora-disk-rekey = {
      inherit (imageProbe.config.systemd.services.aurora-disk-rekey) description unitConfig;
      environment.AURORA_UNIX_CHKPWD = "${pkgs.pam}/bin/unix_chkpwd";
      serviceConfig = imageProbe.config.systemd.services.aurora-disk-rekey.serviceConfig // {
        ExecStartPre = pkgs.writeShellScript "wait-for-rekey-fixture" ''
          while [ ! -e /run/allow-rekey-fixture ]; do sleep 0.1; done
        '';
      };
    };
  };
  testScript = builtins.readFile ./firstboot-rekey.py;
}
