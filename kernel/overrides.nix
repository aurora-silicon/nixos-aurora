# Translate NixOS patch settings into Kconfig fragments and conservative
# capability metadata, without changing the shared distribution baseline.
{ lib, nixpkgsPath, writeText, kernelPatches }:
let
  structuredConfig = (lib.evalModules {
    modules = [
      (nixpkgsPath + "/nixos/modules/system/boot/kernel_config.nix")
      { settings = { }; }
    ] ++ map (patch:
      assert lib.assertMsg (!(patch ? extraStructuredConfig))
        "Use structuredExtraConfig, not extraStructuredConfig, in boot.kernelPatches";
      { settings = patch.structuredExtraConfig or { }; }
    ) kernelPatches;
  }).config.intermediateNixConfig;
  kconfigValue = value:
    if builtins.elem value [ "y" "m" "n" ]
      || builtins.match "(-?[0-9]+|0[xX][0-9a-fA-F]+)" value != null
      || (lib.hasPrefix "\"" value && lib.hasSuffix "\"" value)
    then value else builtins.toJSON value;
  stripComment = line: (lib.foldl' (state: character:
    if state.stopped then state else if character == "#" && !state.quoted then
      state // { stopped = true; }
    else {
      text = state.text + character;
      quoted = if character == "\"" && !state.escaped then !state.quoted else state.quoted;
      escaped = character == "\\" && !state.escaped;
      stopped = false;
    }
  ) { text = ""; quoted = false; escaped = false; stopped = false; }
    (lib.stringToCharacters line)).text;
  # NixOS's structured settings and legacy FOO y lines use the same
  # intermediate format. Merge them after the distribution's base configs.
  requests = lib.concatMap (line:
    let
      trimmed = lib.strings.trim (stripComment line);
      matched = builtins.match "([A-Za-z0-9_]+)(\\?)?([[:blank:]]+(.*))?" trimmed;
    in lib.optional (trimmed != "" && !(lib.hasPrefix "#" trimmed)) (
      assert lib.assertMsg (matched != null) "Invalid kernel extraConfig line: ${line}";
      {
        name = "CONFIG_${builtins.elemAt matched 0}";
        value = let value = builtins.elemAt matched 3; in kconfigValue (if value == null then "" else value);
        optional = builtins.elemAt matched 1 != null;
      }
    )
  ) (lib.splitString "\n" (structuredConfig + "\n"
    + lib.concatMapStringsSep "\n" (patch: patch.extraConfig or "") kernelPatches));
  requested = lib.foldl' (settings: request: settings // {
    ${request.name} = request;
  }) { } requests;
  fragment = request: if request.value == "n"
    then "# ${request.name} is not set\n"
    else "${request.name}=${request.value}\n";
  configOverrides = writeText "aurora-kernel-overrides.config"
    (lib.concatMapStrings fragment (lib.attrValues requested));
  requiredOverrides = writeText "aurora-kernel-required-overrides.config"
    (lib.concatMapStrings fragment (lib.filter (request: !request.optional) (lib.attrValues requested)));
  optionalRequests = lib.filter (request: request.optional) (lib.attrValues requested);
  optionalDefaults = writeText "aurora-kernel-optional-defaults.config"
    (lib.concatMapStrings (request: "# ${request.name} is not set\n") optionalRequests);
  optionalPattern = lib.concatMapStringsSep "|" (request: request.name) optionalRequests;
in {
  inherit requests configOverrides requiredOverrides optionalRequests optionalDefaults optionalPattern;
  guaranteedConfig = lib.mapAttrs (_: request: request.value)
    (lib.filterAttrs (_: request: !request.optional) requested);
}
