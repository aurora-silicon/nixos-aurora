{ pkgs, nixpkgs, makeSystem }:
let
  inherit (nixpkgs) lib;
  # speakerguardd v2 is the only speaker stack: on with the platform, with
  # aurora-speaker-upgrade (run at boot); speakersafetyd and speakerguardd 0.1
  # are not shipped and no unit of theirs can start.
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
in assert lib.assertMsg (lib.all (entry: entry.assertion) on.assertions
     && lib.count (entry: !entry.assertion) incompatible.assertions == 1)
     "The v2 module must accept the current package and reject an incompatible kernel interface";
   assert lib.assertMsg (pkg.pname == "speakerguardd-v2"
     && builtins.elem pkg on.environment.systemPackages && builtins.elem pkg on.systemd.packages)
     "enable = true must install speakerguardd 1.0";
   assert lib.assertMsg (builtins.elem "multi-user.target" (unit "speakerguardd-v2.service").wantedBy)
     "speakerguardd-v2.service must be wanted by multi-user.target when enabled";
   assert lib.assertMsg ((on.systemd.units ? "speakersafetyd.service")
     && !on.systemd.units."speakersafetyd.service".enable
     && !(on.systemd.units ? "speakerguardd.service")
     && !(lib.any (p: (p.pname or "") == "speakerguardd") on.systemd.packages))
     "speakersafetyd.service must be masked and speakerguardd 0.1 must not be installed";
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
     ${pkgs.python3}/bin/python3 -I - "$lx" "$p/share/speakerguardd/gate.json" <<'PY'
     import json
     import os
     import sys
     os.environ.pop("SGV2_GATE", None)
     sys.path.insert(0, sys.argv[1])
     import gen
     with open(sys.argv[2]) as source:
         assert gen.load_gate() == json.load(source)
     PY
     # Session handoff runs inside these units, without the interactive
     # shell's PATH. Both privilege tools must be available there.
     ${pkgs.python3}/bin/python3 -I - <<'PY'
     import os
     import subprocess
     paths = ${builtins.toJSON (builtins.mapAttrs (_: service: lib.makeBinPath service.path) {
       inherit (on.systemd.services)
         speakerguardd-v2-provision speakerguardd-v2-selfcheck
         speakerguardd-v2-switchtest speakerguardd-v2-seat speakerguardd-v2-sleep;
     })}
     for unit, path in paths.items():
         for tool in ("setpriv", "runuser"):
             result = subprocess.run([tool, "--version"], env={**os.environ, "PATH": path},
                                     capture_output=True, text=True)
             assert result.returncode == 0, (unit, tool, result.stderr)
     PY
     LV2_PATH=${lib.escapeShellArg (lib.makeSearchPath "lib/lv2" on.services.pipewire.extraLv2Packages)} \
       ${pkgs.lilv}/bin/lv2ls > plugins
     grep -Fx 'https://aurora-silicon.org/lv2/sgv2#6ch-vi' plugins
     grep -Fx 'https://aurora-silicon.org/lv2/sgv2#voicing-6ch' plugins
     grep -q "$p/share/speakerguardd/parity.json" $lx/speakerguardd-selfcheck
     grep -qx "ExecStart=$lx/speakerguardd \$SGV2_ARGS" $p/lib/systemd/system/speakerguardd-v2.service
     grep -qx "ExecStart=$lx/speakerguardd-provision run" $p/lib/systemd/system/speakerguardd-v2-provision.service
     test -f $p/lib/systemd/system/speakerguardd-v2-seat.path
     test -f $p/lib/systemd/user/speakerguardd-v2-graph.service
     grep -q "$p/share/speakerguardd/gate.json" $lx/speakerguardd-gate
     test ! -e $p/bin/speakerguardd
     # nixos-apple-silicon's sound module adds speakersafetyd: it is empty here.
     test -z "$(ls -A ${enabled.pkgs.speakersafetyd})"
     # No Asahi speaker graph or FIR; the microphone graphs stay.
     a=${enabled.pkgs.asahi-audio}
     test -z "$(find $a/share/asahi-audio \( -name 'graph*.json' -o -name '*.wav' \) -print)"
     test -s $a/share/asahi-audio/j616/mic.json
     touch $out
   ''
