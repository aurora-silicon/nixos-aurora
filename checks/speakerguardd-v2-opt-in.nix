{ pkgs, nixpkgs, makeSystem }:
let
  inherit (nixpkgs) lib;
  # speakerguardd v2 is on by default: it installs beside the legacy daemons
  # behind its gate, which keeps speakersafetyd in charge until
  # aurora-speaker-upgrade (run at boot) switches the Mac.
  enabled = makeSystem "minimal";
  on = enabled.config;
  incompatible = (enabled.extendModules {
    modules = [ {
      aurora.speakerguardd.v2.package = pkgs.speakerguardd-v2.overrideAttrs (old: {
        passthru = old.passthru // { dualInterface = false; };
      });
    } ];
  }).config;
  pkg = on.aurora.speakerguardd.v2.package;
  unit = name: on.systemd.units.${name} or { enable = false; wantedBy = [ ]; text = ""; };
  gate = builtins.unsafeDiscardStringContext "${pkg}/libexec/speakerguardd-v2/speakerguardd-gate legacy";
  gated = name: lib.hasInfix "ExecCondition=+${gate}" (unit "${name}.service").text;
in assert lib.assertMsg (lib.all (entry: entry.assertion) on.assertions
     && lib.count (entry: !entry.assertion) incompatible.assertions == 1)
     "The v2 module must accept the current package and reject an incompatible kernel interface";
   assert lib.assertMsg (pkg.pname == "speakerguardd-v2"
     && builtins.elem pkg on.environment.systemPackages && builtins.elem pkg on.systemd.packages)
     "enable = true must install speakerguardd 1.0";
   assert lib.assertMsg (builtins.elem "multi-user.target" (unit "speakerguardd-v2.service").wantedBy)
     "speakerguardd-v2.service must be wanted by multi-user.target when enabled";
   assert lib.assertMsg (gated "speakersafetyd" && gated "speakerguardd"
     && lib.hasInfix "use-feedback-guard" (unit "speakersafetyd.service").text)
     "the legacy daemons stay enabled behind the gate, beside their own ExecCondition";
   assert lib.assertMsg (on.aurora.speakerguardd.upgrade.enable
     && builtins.elem "multi-user.target" (unit "aurora-speaker-upgrade.service").wantedBy)
     "aurora-speaker-upgrade must run at boot on the image";
   pkgs.runCommand "speakerguardd-v2-package-check" { } ''
     p=${pkgs.speakerguardd-v2}
     lx=$p/libexec/speakerguardd-v2
     test -x $lx/speakerguardd
     test -x $lx/speakerguardd-provision
     test -x $lx/speakerguardd-gate
     test -x $lx/speakerguardd-selfcheck
     test -x $p/bin/aurora-speaker-tuning
     test -f $p/lib/lv2/sgv2.lv2/manifest.ttl
     test -f $p/lib/lv2/sgv2.lv2/libsgv2_lv2.so
     test -f $p/share/speakerguardd/gate.json
     test -f $p/share/speakerguardd/parity.json
     grep -q "$p/share/speakerguardd/parity.json" $lx/speakerguardd-selfcheck
     grep -qx "ExecStart=$lx/speakerguardd \$SGV2_ARGS" $p/lib/systemd/system/speakerguardd-v2.service
     grep -qx "ExecStart=$lx/speakerguardd-provision run" $p/lib/systemd/system/speakerguardd-v2-provision.service
     test -f $p/lib/systemd/system/speakerguardd-v2-seat.path
     test -f $p/lib/systemd/user/speakerguardd-v2-graph.service
     grep -q "$p/share/speakerguardd/gate.json" $lx/speakerguardd-gate
     test ! -e $p/bin/speakerguardd
     touch $out
   ''
