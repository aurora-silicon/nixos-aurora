{ nixpkgs, pkgs, configurations }:
let
  inherit (nixpkgs) lib;
  isoUUID = "6fbaf188-05e0-496a-9885-d6ddfdb4e03e";
  rolesOf = config:
    config.services.pipewire.wireplumber.extraConfig."50-aurora-le-audio"."monitor.bluez.properties"."bluez5.roles";
  probe = configurations.aurora-minimal;
  disabled = (probe.extendModules {
    modules = [ { aurora.bluetooth.leAudio.enable = false; } ];
  }).config;
  disabledGeneral = disabled.hardware.bluetooth.settings.General or { };
  overridden = (probe.extendModules {
    modules = [ {
      hardware.bluetooth.settings.General = {
        Experimental = false;
        KernelExperimental = false;
      };
      services.pipewire.wireplumber.extraConfig."50-aurora-le-audio".
        "monitor.bluez.properties"."bluez5.roles" = [ "a2dp_sink" ];
    } ];
  }).config;
  expectations = {
    "every image enables LE Audio alongside classic audio" = lib.all (value:
      let config = value.config; in
      config.hardware.bluetooth.settings.General.Experimental
      && config.hardware.bluetooth.settings.General.KernelExperimental == isoUUID
      && lib.all (role: lib.elem role (rolesOf config))
        [ "a2dp_sink" "a2dp_source" "bap_sink" "bap_source" "hfp_hf" "hfp_ag" ]
    ) (lib.attrValues configurations);
    "opt out removes Aurora's BlueZ and WirePlumber settings" =
      !(disabledGeneral ? Experimental)
      && !(disabledGeneral ? KernelExperimental)
      && !(disabled.services.pipewire.wireplumber.extraConfig ? "50-aurora-le-audio");
    "ordinary settings override the defaults without mkForce" =
      !overridden.hardware.bluetooth.settings.General.Experimental
      && overridden.hardware.bluetooth.settings.General.KernelExperimental == false
      && rolesOf overridden == [ "a2dp_sink" ];
  };
in pkgs.runCommand "aurora-bluetooth-le-audio-defaults" {
  failures = lib.concatStringsSep "\n" (lib.attrNames (lib.filterAttrs (_: met: !met) expectations));
} ''
  if [[ -n "$failures" ]]; then printf '%s\n' "$failures" >&2; exit 1; fi
  touch $out
''
