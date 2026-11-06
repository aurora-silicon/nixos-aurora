{ pkgs, nixpkgs, makeSystem }:
let
  inherit (nixpkgs) lib;
  profile = makeSystem "minimal";
  inherit (profile) config;
  unit = name: config.systemd.units.${name} or { enable = false; text = ""; };
  guarded = name: lib.hasInfix "speakerguardd-gate" (unit name).text;
  preview = package: (package.pname or "") == "speakerguardd-v2";
in assert lib.assertMsg (!config.aurora.speakerguardd.v2.enable)
     "The v2 rollout is held";
   assert lib.assertMsg (!(lib.any preview config.environment.systemPackages)
     && !(lib.any preview config.systemd.packages)) "The image must not install v2";
   # Services imported from systemd.packages do not all appear in
   # config.systemd.units. Check their package imports here, and the
   # actual packaged unit files in the derivation below.
   assert lib.assertMsg (lib.all (package: lib.elem package config.systemd.packages)
     [ profile.pkgs.speakersafetyd profile.pkgs.speakerguardd ]
     && !(guarded "speakersafetyd.service") && !(guarded "speakerguardd.service"))
     "Legacy daemons must remain available without the v2 gate";
   assert lib.assertMsg (lib.hasInfix "use-feedback-guard" (unit "speakersafetyd.service").text)
     "Keep the board-specific legacy protection selector";
   assert lib.assertMsg (config.boot.kernelPackages.kernel.auroraLegacySpeakerProtection or false)
     "The image kernel must support legacy speaker protection";
   pkgs.runCommandNoCC "aurora-legacy-speaker-graphs" { } ''
     test -s ${profile.pkgs.speakersafetyd}/lib/systemd/system/speakersafetyd.service
     test -s ${profile.pkgs.speakerguardd}/lib/systemd/system/speakerguardd.service
     for board in j316 j413 j616 j700; do
       test -s ${profile.pkgs.asahi-audio}/share/asahi-audio/$board/graph.json
     done
     test -s ${profile.pkgs.asahi-audio}/share/asahi-audio/j700/48.wav
     touch $out
   ''
