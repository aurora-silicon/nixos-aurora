{ pkgs, nixpkgs, self, imageProbe }:
let
  inherit (nixpkgs) lib;
  kde = self.nixosConfigurations.aurora-kde.config;
  gnome = self.nixosConfigurations.aurora-gnome.config;
  minimal = self.nixosConfigurations.aurora-minimal.config;
  firstboot = imageProbe.config.systemd.services.aurora-firstboot;
  plasmaSetup = kde.systemd.services.plasma-setup;
  plasmaSetupPackage = self.nixosConfigurations.aurora-kde.pkgs.kdePackages.plasma-setup;
  gnomePkgs = self.nixosConfigurations.aurora-gnome.pkgs;
  installs = packages: lib.any (package: package.pname or "" == "plasma-setup") packages;
  patchedWith = name: package: lib.any (patch: lib.hasSuffix "-${name}" (toString patch)) (package.patches or [ ]);
  launchAuth = lib.splitString "\n" gnome.security.pam.services.gdm-launch-environment.text;
  autologinAuth = lib.filter (lib.hasPrefix "auth ")
    (lib.splitString "\n" kde.security.pam.services.plasmalogin-autologin.text);
  greeter = kde.systemd.services.plasmalogin;
  kdeWith = module: (self.nixosConfigurations.aurora-kde.extendModules { modules = [ module ]; }).config;
  # What the rekey writes into owner.nix once the password unlocks the disk.
  kdeRekeyed = kdeWith { aurora.firstboot.passwordHooks = false; };
  kdeGerman = kdeWith { services.xserver.xkb.layout = "de"; };
  kdeGermanFrenchConsole = kdeWith { services.xserver.xkb.layout = "de"; console.keyMap = "fr"; };
  kdeSshAtBoot = kdeWith { aurora.openssh.startAtBoot = true; };
  # Graphical first boot: each failed expectation is reported by name.
  desktopExpectations = {
    "every factory image includes installed-system update commands" = lib.all (profile:
      lib.all (name: lib.any (package: package.name or "" == name) profile.config.environment.systemPackages)
        [ "aurora-update" "aurora-install-stage2" ]
      && !(profile.config.boot.loader.grub.extraFiles ? "m1n1/boot.bin")
      && lib.hasInfix "aurora-install-stage2" profile.config.boot.loader.grub.extraInstallCommands)
      (lib.attrValues self.nixosConfigurations);
    "activation restores per-device firmware after udev changes its path" =
      lib.elem "udevd" minimal.system.activationScripts.auroraFirmwarePath.deps;
    "desktop images boot with the Aurora splash" = kde.boot.plymouth.enable && gnome.boot.plymouth.enable
      && kde.boot.plymouth.theme == "aurora" && gnome.boot.plymouth.theme == "aurora"
      && lib.all (c: lib.any (p: (p.pname or "") == "plymouth-theme-aurora") c.boot.plymouth.themePackages) [ kde gnome ]
      && lib.all (c: lib.hasInfix "DeviceScale=1" c.boot.plymouth.extraConfig) [ kde gnome ];
    "every profile selects the patched Plymouth" = lib.all (c:
      c.boot.plymouth.package.drvPath == pkgs.plymouth.drvPath
      && patchedWith "0001-ply-device-manager-Fix-race-in-fb_device_has_drm_dev.patch" c.boot.plymouth.package
      && patchedWith "0001-ply-device-manager-fix-default-XKB-keymap-fallback-o.patch" c.boot.plymouth.package
      && patchedWith "0001-ply-terminal-Keep-terminal-input-nonblocking.patch" c.boot.plymouth.package
      && patchedWith "0001-Fix-splash-keyboard-lifetime.patch" c.boot.plymouth.package
      && c.boot.plymouth.package.scriptKeyboardLifetime >= 1
      && patchedWith "0002-drm-Reset-inherited-HDR-connector-state-before-SDR.patch" c.boot.plymouth.package
      && c.boot.plymouth.package.doCheck) [ kde gnome minimal ];
    "minimal images boot without a splash" = !minimal.boot.plymouth.enable;
    "the initrd asks for no TPM drivers, which the shared kernel lacks" = lib.all (c:
      !(lib.elem "tpm-tis" c.boot.initrd.availableKernelModules)
      && !(lib.elem "tpm-crb" c.boot.initrd.availableKernelModules)) [ kde gnome minimal ];
    "every image has an OpenSSH server that starts only on request" = lib.all (c:
      c.services.openssh.enable && !c.services.openssh.startWhenNeeded
      && c.systemd.services.sshd.wantedBy == [ ] && c.systemd.services.sshd-keygen.wantedBy == [ ]
      && lib.elem "sshd-keygen.service" c.systemd.services.sshd.wants
      && !(lib.elem 22 c.networking.firewall.allowedTCPPorts)) [ kde gnome minimal ];
    "aurora.openssh.startAtBoot starts the OpenSSH server at boot" =
      lib.elem "multi-user.target" kdeSshAtBoot.systemd.services.sshd.wantedBy
      && lib.elem "multi-user.target" kdeSshAtBoot.systemd.services.sshd-keygen.wantedBy;
    "desktop images start graphical.target" = kde.systemd.defaultUnit == "graphical.target"
      && gnome.systemd.defaultUnit == "graphical.target";
    "the splash quits only after first-boot setup" = !(lib.elem "plymouth-quit.service" firstboot.after)
      && lib.elem "aurora-firstboot.service" kde.systemd.services.plymouth-quit.after
      && lib.elem "aurora-firstboot.service" gnome.systemd.services.plymouth-quit.after;
    "first boot runs while pending, or for aurora.firstboot=text" =
      firstboot.unitConfig.ConditionPathExists == "|/var/lib/aurora/firstboot/pending"
      && firstboot.unitConfig.ConditionKernelCommandLine == "|aurora.firstboot=text";
    "first boot never takes tty1 from Plymouth" = firstboot.serviceConfig.StandardInput == "null"
      && !(firstboot.serviceConfig ? TTYPath) && !(firstboot.serviceConfig ? TTYVHangup);
    "images create the owner imperatively" = kde.users.mutableUsers && gnome.users.mutableUsers && minimal.users.mutableUsers;
    "Plasma Setup runs on KDE images only" = kde.aurora.plasmaSetup.enable
      && !gnome.aurora.plasmaSetup.enable && !minimal.aurora.plasmaSetup.enable;
    "Plasma Setup is enabled after the disk step" = lib.elem "multi-user.target" plasmaSetup.wantedBy
      && lib.elem "aurora-firstboot.service" plasmaSetup.after
      && plasmaSetup.unitConfig.ConditionPathExists == [ "!/var/lib/aurora/firstboot/pending" "!/var/lib/aurora/firstboot/complete" ];
    "Plasma Setup's unit, D-Bus helper, tmpfiles and polkit files are installed" = installs kde.systemd.packages
      && installs kde.services.dbus.packages && installs kde.systemd.tmpfiles.packages && installs kde.environment.systemPackages;
    "Plasma Setup is patched for NixOS paths" = patchedWith "plasma-setup-nixos-paths.patch" plasmaSetupPackage;
    "Plasma Setup's autostart entry is not executable" =
      kde.systemd.tmpfiles.settings.plasma-setup-xdg-autostart."/run/plasma-setup/.config/autostart/*.desktop".z.mode == "0640";
    "the setup user is a system user with its sysusers home" = kde.users.users.plasma-setup.isSystemUser
      && kde.users.users.plasma-setup.home == "/run/plasma-setup" && kde.users.groups ? plasma-setup;
    "KDE signs in with Plasma Login Manager, whose greeter runs on KWin Wayland, not SDDM" =
      kde.services.displayManager.plasma-login-manager.enable && !kde.services.displayManager.sddm.enable
      && !gnome.services.displayManager.plasma-login-manager.enable
      && !minimal.services.displayManager.plasma-login-manager.enable;
    "Plasma Login is the display-manager.service alias and the only KDE greeter unit" =
      lib.elem "display-manager.service" greeter.aliases && lib.elem "graphical.target" greeter.wantedBy
      && !(kde.systemd.services ? display-manager);
    "the KDE greeter waits for the disk step" = lib.elem "aurora-firstboot.service" greeter.after
      && greeter.unitConfig.ConditionPathExists == "!/var/lib/aurora/firstboot/pending";
    "Plasma Login may log the setup user in automatically: no UID floor" = autologinAuth != [ ]
      && !(lib.any (lib.hasInfix "pam_succeed_if.so") autologinAuth);
    "Plasma Login reads Plasma Setup's autologin from /etc/plasmalogin.conf.d" =
      kde.environment.etc ? "plasmalogin.conf.d/00-nixos-defaults.conf";
    "Plasma Setup's autologin session exists" = lib.elem "plasma" kde.services.displayManager.sessionData.sessionNames;
    "the Nix build users are not counted as accounts" = kde.security.loginDefs.settings.UID_MAX < kde.ids.uids.nixbld;
    "Plasma Login keeps the splash for the disk password, as GDM does" =
      lib.elem "plymouth-quit.service" greeter.conflicts && lib.elem "plymouth-quit.service" greeter.onFailure
      && kde.systemd.services.plymouth-quit.wantedBy == [ ]
      && lib.elem "plymouth-quit.service" gnome.systemd.services.display-manager.conflicts;
    "GNOME Initial Setup runs on GNOME images only" = gnome.aurora.gnomeInitialSetup.enable
      && gnome.services.gnome.gnome-initial-setup.enable
      && !kde.aurora.gnomeInitialSetup.enable && !minimal.aurora.gnomeInitialSetup.enable;
    "GDM finds GNOME Initial Setup's session in the system profile" =
      gnome.services.displayManager.generic.execCmd == "exec ${gnomePkgs.aurora-gdm}/bin/gdm"
      && patchedWith "gdm-initial-setup-session-path.patch" gnomePkgs.aurora-gdm
      && lib.any (package: package.pname or "" == "gnome-initial-setup") gnome.services.displayManager.gdm.extraPackages;
    "GNOME Initial Setup keeps its account and password pages" =
      lib.any (lib.hasInfix "aurora-gnome-initial-setup-vendor.conf") gnomePkgs.gnome-initial-setup.mesonFlags;
    "GDM runs the setup session as its gnome-initial-setup users" =
      lib.all (name: let user = gnome.users.users.${name} or { }; in
        user.isSystemUser or false && user.group or "" == "gnome-initial-setup"
        && user.home or "" == "/run/gdm/home/${name}")
        [ "gnome-initial-setup" "gnome-initial-setup-2" "gnome-initial-setup-5" ]
      && lib.length (lib.filter (lib.hasInfix "user ingroup gdm:gnome-initial-setup") launchAuth) == 3;
    "the setup session keeps gnome-session's template" =
      gnome.systemd.user.targets."gnome-session@gnome-initial-setup".overrideStrategy == "asDropin";
    "GDM's setup-done marker is cleared only before the display manager starts" =
      lib.elem "display-manager.service" gnome.systemd.services.aurora-gnome-initial-setup.wantedBy
      && lib.elem "display-manager.service" gnome.systemd.services.aurora-gnome-initial-setup.before
      && gnome.systemd.services.aurora-gnome-initial-setup.unitConfig.ConditionPathExists == "/run/gdm/gdm.ran-initial-setup";
    "GNOME declares its account setup to aurora-firstboot" =
      gnome.environment.etc."aurora/desktop-account-setup".text == "gnome-initial-setup\n"
      && !(kde.environment.etc ? "aurora/desktop-account-setup")
      && !(minimal.environment.etc ? "aurora/desktop-account-setup");
    "the first password sign-in hooks are declared until the rekey" =
      kde.security.pam.services.plasmalogin.rules.auth ? aurora-password-hook
      && kde.security.pam.services.plasmalogin-autologin.rules.auth ? aurora-password-gate
      && lib.hasInfix "aurora-password-hook" kde.security.pam.services.plasmalogin.text
      && gnome.security.pam.services.gdm-password.rules.auth ? aurora-password-hook
      && kde.environment.etc."aurora/password-hooks".text == "plasmalogin plasmalogin-autologin\n"
      && gnome.environment.etc."aurora/password-hooks".text == "gdm-password\n";
    "a rebuild after the rekey removes the hooks" =
      !(kdeRekeyed.security.pam.services.plasmalogin.rules.auth ? aurora-password-hook)
      && !(kdeRekeyed.security.pam.services.plasmalogin-autologin.rules.auth ? aurora-password-gate)
      && !(lib.hasInfix "aurora-password-hook" kdeRekeyed.security.pam.services.plasmalogin.text)
      && !(kdeRekeyed.environment.etc ? "aurora/password-hooks");
    "the console keymap follows the XKB layout unless set" = kde.console.keyMap == "us"
      && lib.hasSuffix "-xkb-console-keymap" (toString kdeGerman.console.keyMap)
      && kdeGermanFrenchConsole.console.keyMap == "fr"
      && lib.hasInfix "layout=de\n" kdeGerman.environment.etc."aurora/keyboard".text;
    "the initrd unlock prompt waits for the console keymap" = lib.elem "systemd-vconsole-setup.service"
      imageProbe.config.boot.initrd.systemd.services.aurora-initrd-root.after;
    "NetworkManager's dispatcher stays on the bus until NetworkManager stops" = lib.all (c: let
        dispatcher = c.systemd.services.NetworkManager-dispatcher;
      in lib.elem "NetworkManager.service" dispatcher.before
        && dispatcher.serviceConfig.ExecStart
          == [ "" "${c.networking.networkmanager.package}/libexec/nm-dispatcher --persist" ])
      [ kde gnome minimal ];
    "systemd-modules-load asks only for modules this kernel provides" = lib.all (c: let
        conf = lib.splitString "\n" c.environment.etc."modules-load.d/nixos.conf".source.text;
      in lib.elem "loop" conf && !(lib.elem "atkbd" conf) && !(lib.elem "cpufreq_schedutil" conf))
      [ kde gnome minimal ];
    # dbus-broker logs "Ignoring duplicate name" for each service file
    # it reads a second time (modules/dbus.nix).
    "each bus reads every D-Bus service directory once" = lib.all (c: let
        sw = toString c.system.path;
        linked = map toString (lib.concatMap (output: output.paths) c.system.path.chosenOutputs);
        dirs = c.environment.etc."dbus-1".source.busServiceDirectories or { system = [ ]; session = [ sw ]; };
        once = list: list == lib.unique list && !(lib.any (p: p != sw && lib.elem p linked) list);
      in once dirs.system && once dirs.session && lib.elem sw dirs.system && !(lib.elem sw dirs.session)
        && lib.any (line: lib.hasPrefix "XDG_DATA_DIRS " line && lib.hasInfix "/run/current-system/sw/share" line)
          (lib.splitString "\n" c.environment.etc."pam/environment".text))
      [ kde gnome minimal ];
  };
in pkgs.runCommand "aurora-firstboot-image-evaluation" {
  rootUnit = let
    units = imageProbe.config.boot.initrd.systemd.units;
  in lib.concatMapStrings (name: units.${name}.text)
    (lib.filter (lib.hasPrefix "dev-disk-by\\x2duuid-") (lib.attrNames units));
  desktopFailures = lib.concatStringsSep "\n" (lib.attrNames (lib.filterAttrs (_: met: !met) desktopExpectations));
  stage2Preserved = if builtins.hasAttr "m1n1/boot.bin" imageProbe.config.boot.loader.grub.extraFiles
    || builtins.hasAttr "m1n1/boot.bin" minimal.boot.loader.grub.extraFiles
    || !(nixpkgs.lib.hasInfix "aurora-install-stage2" imageProbe.config.boot.loader.grub.extraInstallCommands)
    || imageProbe.config.system.autoUpgrade.enable
    then "0" else "1";
  units = builtins.toJSON {
    firstboot = imageProbe.config.systemd.services.aurora-firstboot.serviceConfig;
    initrd = imageProbe.config.boot.initrd.systemd.services.aurora-initrd-root.serviceConfig;
    kernelModules = imageProbe.config.boot.initrd.kernelModules;
    sysroot = imageProbe.config.boot.initrd.systemd.units."sysroot.mount".text;
    rootDevice = imageProbe.config.boot.initrd.systemd.units."dev-mapper-root.device".text;
    mounts = map (mount: { inherit (mount) what where; }) imageProbe.config.boot.initrd.systemd.mounts;
    layout = imageProbe.config.aurora.imageLayout;
  };
} ''
  [[ "$stage2Preserved" == 1 ]] || { echo 'installed rebuilds must install Stage 2 through aurora-install-stage2 only, and never upgrade unattended' >&2; exit 1; }
  if [[ -n "$desktopFailures" ]]; then
    printf 'graphical first boot: %s\n' "$desktopFailures" >&2
    exit 1
  fi
  case "$units" in
    *'What=/dev/mapper/root'*) echo 'initrd sysroot must not wait for the mapper of a root that may stay plaintext' >&2; exit 1 ;;
  esac
  case "$rootUnit" in
    *'JobRunningTimeoutSec=infinity'*) ;;
    *) echo 'initrd root device must not time out during first-boot conversion' >&2; exit 1 ;;
  esac
  case "$units" in
    *'JobRunningTimeoutSec=infinity'*) ;;
    *) echo 'initrd root mapper must not time out during first-boot conversion' >&2; exit 1 ;;
  esac
  case "$units" in
    *'modprobe apple_wdt'*) ;;
    *) echo 'initrd must take over the watchdog before conversion' >&2; exit 1 ;;
  esac
  printf '%s\n' "$units" > $out
''
