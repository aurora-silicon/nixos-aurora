{ pkgs, nixpkgs, makeSystem }:
# Fix switches folded into always-on behavior keep a removal module, so a
# configuration that still sets one fails with the removal message (an
# assertion naming the option and its replacement) instead of an
# unknown-option error.
let
  inherit (nixpkgs) lib;
  removed = {
    "aurora.systemFixes.nmDispatcherPersist" = "--persist";
    "aurora.systemFixes.drkonqiOrdering" = "KDE bug 528003";
    "aurora.systemFixes.nmKeepWakeOnLan" = "Wake-on-LAN/WLAN";
    "aurora.audio.pipewireFixes" = "aurora-pipewire";
  };
  base = makeSystem "minimal";
  failing = config: lib.filter (entry: !entry.assertion) config.assertions;
  check = name: reason:
    let
      path = lib.splitString "." name;
      result = builtins.tryEval (failing (base.extendModules {
        modules = [ (lib.setAttrByPath path false) ];
      }).config);
      messages = map (entry: entry.message) result.value;
    in assert lib.assertMsg result.success
         "setting ${name} must evaluate to the removal assertion, not an unknown-option error";
       assert lib.assertMsg (lib.length messages == 1
         && lib.hasPrefix "The option definition `${name}' in " (lib.head messages)
         && lib.hasInfix "no longer has any effect; please remove it." (lib.head messages)
         && lib.hasInfix reason (lib.head messages))
         "setting ${name} must fail with exactly its removal message, got: ${builtins.toJSON messages}";
       name;
in assert lib.assertMsg (failing base.config == [ ])
     "the minimal system must not trip a removal assertion";
   pkgs.writeText "aurora-removed-options-check"
     (lib.concatLines (lib.mapAttrsToList check removed))
