{ pkgs, nixpkgs, self }:
let
  inherit (nixpkgs) lib;
  auth = c: name: lib.filter (lib.hasPrefix "auth ")
    (lib.splitString "\n" (c.security.pam.services.${name}.text or ""));
  offers = c: name: lib.any (lib.hasInfix "/pam_fprintd.so") (auth c name);
  # pam_fprintd only as "sufficient", with the password after it.
  orPassword = c: name: let
    lines = auth c name;
    index = lib.lists.findFirstIndex (lib.hasInfix "/pam_fprintd.so") null lines;
  in index != null
    && lib.all (line: !(lib.hasInfix "/pam_fprintd.so" line) || lib.hasPrefix "auth sufficient " line) lines
    && lib.any (lib.hasInfix "/pam_unix.so") (lib.drop index lines);
  failures = lib.concatMap (value: let c = value.config; kde = c.aurora.desktop == "kde"; in
    lib.mapAttrsToList (name: _: "${c.aurora.desktop}: ${name}") (lib.filterAttrs (_: passed: !passed) {
      "sudo takes a fingerprint or the password" = orPassword c "sudo";
      "polkit takes a fingerprint or the password" = orPassword c "polkit-1";
      "the console login, su and ssh ask for the password" =
        !(offers c "login") && !(offers c "su") && !(offers c "sshd");
      "the login screen asks for the password" = if kde
        then !(offers c "plasmalogin") && !(offers c "kde")
        else c.aurora.desktop != "gnome" || !(offers c "gdm-password");
      "the lock screen takes a fingerprint" = if kde then offers c "kde-fingerprint"
        else c.aurora.desktop != "gnome" || offers c "gdm-fingerprint";
      "a short power-button press suspends" = c.services.logind.settings.Login.HandlePowerKey == "suspend"
        && c.services.logind.settings.Login.HandlePowerKeyLongPress == "poweroff"
        && (!kde || lib.hasInfix "PowerButtonAction=1" (builtins.readFile c.environment.etc."xdg/powerdevilrc".source));
    })) (lib.attrValues self.nixosConfigurations);
in assert lib.assertMsg (failures == [ ]) "Touch ID PAM policy: ${lib.concatStringsSep "; " failures}";
  pkgs.runCommand "aurora-touchid-pam" { } "touch $out"
