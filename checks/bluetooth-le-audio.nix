{ nixpkgs, pkgs, configurations }:
let
  inherit (nixpkgs) lib;
  isoUUID = "6fbaf188-05e0-496a-9885-d6ddfdb4e03e";
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
      services.pipewire.wireplumber.extraConfig."99-owner-bluetooth".
        "monitor.bluez.properties"."bluez5.roles" = [ "a2dp_sink" ];
    } ];
  }).config;
  expectations = {
    "every image enables LE Audio with the existing audio stack" = lib.all (value:
      let config = value.config; in
      config.hardware.bluetooth.settings.General.Experimental
      && config.hardware.bluetooth.settings.General.KernelExperimental == isoUUID
      && config.services.pipewire.enable
      && config.services.pipewire.wireplumber.enable
      && !(config.services.pipewire.wireplumber.extraConfig ? "50-aurora-le-audio")
    ) (lib.attrValues configurations);
    "opt out removes Aurora's BlueZ and WirePlumber settings" =
      !(disabledGeneral ? Experimental)
      && !(disabledGeneral ? KernelExperimental)
      && !(disabled.services.pipewire.wireplumber.extraConfig ? "50-aurora-le-audio");
    "ordinary settings override the defaults without mkForce" =
      !overridden.hardware.bluetooth.settings.General.Experimental
      && overridden.hardware.bluetooth.settings.General.KernelExperimental == false
      && overridden.services.pipewire.wireplumber.extraConfig."99-owner-bluetooth".
        "monitor.bluez.properties"."bluez5.roles" == [ "a2dp_sink" ];
  };
in pkgs.runCommand "aurora-bluetooth-le-audio-defaults" {
  failures = lib.concatStringsSep "\n" (lib.attrNames (lib.filterAttrs (_: met: !met) expectations));
} ''
  if [[ -n "$failures" ]]; then printf '%s\n' "$failures" >&2; exit 1; fi
  touch $out
''
