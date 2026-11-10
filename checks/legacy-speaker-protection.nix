{ pkgs, nixpkgs, makeSystem }:
let
  inherit (nixpkgs) lib;
  profile = makeSystem "minimal";
  inherit (profile) config;
  unit = name: config.systemd.units.${name} or { enable = false; text = ""; };
# The legacy protection stays installed and available as the fallback the v2
# gate starts on a Mac aurora-speaker-upgrade has not switched.
in assert lib.assertMsg (config.aurora.speakerguardd.v2.enable && config.aurora.speakerguardd.upgrade.enable)
     "The image ships speakerguardd v2 and aurora-speaker-upgrade";
   # Services imported from systemd.packages do not all appear in
   # config.systemd.units. Check their package imports here, and the
   # actual packaged unit files in the derivation below.
   assert lib.assertMsg (lib.all (package: lib.elem package config.systemd.packages)
     [ profile.pkgs.speakersafetyd profile.pkgs.speakerguardd ])
     "Legacy daemons must remain available as the fallback";
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
