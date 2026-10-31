{ config, lib, ... }:
let
  cfg = config.aurora.bluetooth.leAudio;
in {
  options.aurora.bluetooth.leAudio.enable = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = ''
      Offer LE Audio alongside classic Bluetooth audio. Enables BlueZ's
      experimental D-Bus profiles and only the ISO socket kernel feature.
      Individual BlueZ settings and WirePlumber roles remain overridable.
    '';
  };

  config = lib.mkIf (cfg.enable && config.hardware.bluetooth.enable) {
    hardware.bluetooth.settings.General = {
      Experimental = lib.mkDefault true;
      KernelExperimental = lib.mkDefault "6fbaf188-05e0-496a-9885-d6ddfdb4e03e";
    };
    services.pipewire.wireplumber.extraConfig."50-aurora-le-audio" =
      lib.mkIf config.services.pipewire.enable {
        "monitor.bluez.properties"."bluez5.roles" = lib.mkDefault [
          "a2dp_sink" "a2dp_source" "bap_sink" "bap_source" "hfp_hf" "hfp_ag"
        ];
      };
  };
}
