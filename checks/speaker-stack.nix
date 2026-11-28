{ pkgs, nixpkgs, makeSystem }:
let
  inherit (nixpkgs) lib;
  enabled = makeSystem "minimal";
  on = enabled.config;
  optOutSys = enabled.extendModules {
    modules = [ { aurora.speakers.stack = "speakersafetyd"; } ];
  };
  optOut = optOutSys.config;
  backToV2Sys = optOutSys.extendModules {
    modules = [ { aurora.speakers.stack = lib.mkForce "sgv2"; } ];
  };
  backToV2 = backToV2Sys.config;
  hook = "+${optOutSys.pkgs.aurora-speaker-stack}/bin/aurora-speaker-stack interlock-apply";
in assert lib.assertMsg (on.aurora.speakers.stack == "sgv2"
     && builtins.elem enabled.pkgs.aurora-speaker-stack on.environment.systemPackages
     && on.aurora.speakerguardd.v2.enable
     && on.aurora.speakerguardd.upgrade.enable
     && !on.systemd.units."speakersafetyd.service".enable
     && !(on.environment.etc ? "aurora/speaker-stack.conf"))
     "Default aurora.speakers.stack must be sgv2 with aurora-speaker-stack installed and speakersafetyd masked";
   assert lib.assertMsg (lib.all (entry: entry.assertion) optOut.assertions
     && optOut.aurora.speakers.stack == "speakersafetyd"
     && !optOut.aurora.speakerguardd.v2.enable
     && !optOut.aurora.speakerguardd.upgrade.enable
     && optOut.systemd.units."speakersafetyd.service".enable
     && optOut.systemd.services.speakersafetyd.overrideStrategy == "asDropin"
     && builtins.elem hook optOut.systemd.services.speakersafetyd.serviceConfig.ExecStartPre
     && builtins.elem optOutSys.pkgs.speakersafetyd-nixpkgs optOut.systemd.packages
     && builtins.elem optOutSys.pkgs.speakersafetyd-nixpkgs optOut.services.udev.packages
     && optOut.environment.etc."aurora/speaker-stack.conf".text == "stack=speakersafetyd\n")
     "aurora.speakers.stack = speakersafetyd must disable v2, enable speakersafetyd with interlock-apply drop-in, and write speaker-stack.conf";
   assert lib.assertMsg (lib.all (entry: entry.assertion) backToV2.assertions
     && backToV2.aurora.speakers.stack == "sgv2"
     && backToV2.aurora.speakerguardd.v2.enable
     && backToV2.aurora.speakerguardd.upgrade.enable
     && !backToV2.systemd.units."speakersafetyd.service".enable
     && !(backToV2.environment.etc ? "aurora/speaker-stack.conf"))
     "Switching aurora.speakers.stack back to sgv2 must restore v2 and mask speakersafetyd";
   pkgs.runCommand "aurora-speaker-stack-check" { } ''
     p=${pkgs.aurora-speaker-stack}
     test -x $p/bin/aurora-speaker-stack
     test -f $p/share/man/man8/aurora-speaker-stack.8.gz
     test -f $p/share/doc/aurora-audio/README.md
     $p/bin/aurora-speaker-stack --help >/dev/null
     touch $out
   ''
