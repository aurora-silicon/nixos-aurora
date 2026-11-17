{ pkgs, nixpkgs, makeSystem }:
let
  inherit (nixpkgs) lib;
  withSettings = settings: ((makeSystem "minimal").extendModules {
    modules = [ { aurora.sepLuks = { enable = true; } // settings; } ];
  }).config;
  password = c: name: map (line: builtins.head (lib.splitString " #" line))
    (lib.filter (lib.hasPrefix "password ") (lib.splitString "\n" c.security.pam.services.${name}.text));
  # File names in place of store paths, in module paths and in key=path arguments.
  base = word: let parts = lib.splitString "=" word; in
    if !(lib.hasInfix "/nix/store/" word) then word
    else if lib.length parts == 2 then "${lib.head parts}=${baseNameOf (lib.last parts)}"
    else baseNameOf word;
  shape = map (line: lib.concatStringsSep " " (map base (lib.splitString " " line)));
  initrdUnit = c: c.boot.initrd.systemd.services.aurora-sep-initrd;
  initrdConf = c: c.boot.initrd.systemd.contents."/usr/lib/aurora-sep/initrd.conf".text;
  off = (makeSystem "minimal").config;
  on = withSettings { };
  machine = withSettings { initrd.enable = true; };
  passwordRoot = withSettings { initrd = { enable = true; passwordUnlock = true; keyStore = false; }; };
  noSync = withSettings { passwordSync.enable = false; };
in assert lib.assertMsg (shape (password on "passwd") == [
    "password [success=ok default=2] pam_unix.so nullok"
    "password optional pam_aurora_sep_fde.so helper=aurora-sep-fde-passwd"
    "password sufficient pam_permit.so"
    "password required pam_deny.so"
  ]) "passwd: the disk password follows only a password pam_unix changed (${toString (password on "passwd")})";
   assert lib.assertMsg (password off "passwd" == password noSync "passwd"
     && !(lib.any (lib.hasInfix "pam_aurora_sep_fde") (password on "login")))
     "passwordSync touches only its services, and only when on";
   assert lib.assertMsg (initrdConf machine == "AURORA_SEP_KEYSTORE_ONLY=1\n"
     && builtins.attrNames machine.boot.initrd.secrets == [ "/var/lib/aurora-sep-keybag.bin" "/var/lib/aurora-sep-refkey.bin" ]
     && builtins.elem "/var/lib/aurora-sep-keybag.bin" (initrdUnit machine).unitConfig.ConditionPathExists)
     "machine-sealed volumes: keystore_only=1 with the key store copies";
   assert lib.assertMsg (initrdConf passwordRoot == "AURORA_SEP_KEYSTORE_ONLY=2\n"
     && passwordRoot.boot.initrd.secrets == { }
     && (initrdUnit passwordRoot).unitConfig.ConditionPathExists == [ "/usr/lib/aurora-sep/initrd.conf" ]
     && lib.all (a: a.assertion) passwordRoot.assertions)
     "password-sealed root: keystore_only=2, no key store needed";
   assert lib.assertMsg (builtins.elem "sysinit.target" (initrdUnit machine).wantedBy
     && lib.any (p: lib.hasSuffix "/lib/cryptsetup" (toString (p.source or p))) machine.boot.initrd.systemd.storePaths)
     "the initrd loader starts from sysinit.target and the token plugin is in the initrd";
   pkgs.runCommand "aurora-sep-luks-module" { } "touch $out"
