{ pkgs, nixpkgs, makeSystem }:
let
  inherit (nixpkgs) lib;
  profile = makeSystem "minimal";
  inherit (profile) config;
  optedOut = (profile.extendModules {
    modules = [ { aurora.speakers.stack = "speakersafetyd"; } ];
  }).config;
# Default installs ship speakerguardd v2 and aurora-speaker-upgrade with no
# legacy speaker daemon and no Asahi speaker DSP graphs. Setting
# aurora.speakers.stack = "speakersafetyd" is the explicit user opt-out.
in assert lib.assertMsg (config.aurora.speakers.stack == "sgv2"
     && config.aurora.speakerguardd.v2.enable
     && config.aurora.speakerguardd.upgrade.enable)
     "The default image must run speakerguardd v2 and aurora-speaker-upgrade";
   assert lib.assertMsg (!(lib.elem profile.pkgs.speakersafetyd config.systemd.packages)
     && !(lib.elem profile.pkgs.speakersafetyd config.services.udev.packages))
     "Default image must not install speakersafetyd units or udev rules";
   assert lib.assertMsg (lib.elem profile.pkgs.aurora-speaker-stack config.environment.systemPackages)
     "Default image must ship aurora-speaker-stack";
   assert lib.assertMsg (!optedOut.aurora.speakerguardd.v2.enable
     && !optedOut.aurora.speakerguardd.upgrade.enable
     && lib.elem profile.pkgs.speakersafetyd optedOut.systemd.packages
     && lib.elem profile.pkgs.speakersafetyd optedOut.services.udev.packages
     && optedOut.environment.etc."aurora/speaker-stack.conf".text == "stack=speakersafetyd\n")
     "Explicit speakersafetyd opt-out must disable v2 and enable speakersafetyd";
   pkgs.runCommand "aurora-no-legacy-speaker-graphs" { } ''
     audio=${profile.pkgs.asahi-audio}
     test -z "$(find "$audio/share/asahi-audio" \( -name 'graph*.json' -o -name '*.wav' \) -print)"
     test ! -e "$audio/share/wireplumber/scripts/device/asahi-lock-volume.lua"
     if grep -Eq 'graph[^"/]*\.json|RawSpeakers|asahi-lock-volume' \
         "$audio/share/wireplumber/wireplumber.conf.d/99-asahi.conf"; then
       echo '99-asahi.conf still carries a speaker graph or lock' >&2
       exit 1
     fi
     for board in j293 j313 j314 j316 j413 j415 j604 j614 j616 j700 j714; do
       test -s "$audio/share/asahi-audio/$board/mic.json"
     done
     test -x ${profile.pkgs.aurora-speaker-stack}/bin/aurora-speaker-stack
     test -s ${profile.pkgs.aurora-speaker-stack}/share/man/man8/aurora-speaker-stack.8
     test -s ${profile.pkgs.aurora-speaker-stack}/share/doc/aurora-audio/README.md
     touch $out
   ''
