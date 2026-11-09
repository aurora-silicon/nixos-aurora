{ pkgs, nixpkgs, self }:
let
  inherit (nixpkgs) lib;
  evaluated = lib.nixosSystem {
    system = pkgs.stdenv.hostPlatform.system;
    modules = [
      self.inputs.apple-silicon.nixosModules.default
      self.nixosModules.default
      self.nixosModules.installed
      {
        nixpkgs.overlays = [ self.inputs.apple-silicon.overlays.default self.overlays.default ];
        system.stateVersion = "26.05";
      }
    ];
  };
  optionData = (pkgs.nixosOptionsDoc {
    options = { inherit (evaluated.options) aurora; };
    transformOptions = option: option // {
      declarations = map (file:
        assert lib.assertMsg (lib.hasPrefix "${self}/" (toString file))
          "Aurora option declarations must point into this repository";
        "https://github.com/aurora-silicon/nixos-aurora/blob/main/"
          + lib.removePrefix "${self}/" (toString file)
      ) option.declarations;
    };
  }).optionsNix;
  # Documentation metadata must not pull package defaults into the build closure.
  optionsFile = pkgs.writeText "aurora-options.json"
    (builtins.unsafeDiscardStringContext (builtins.toJSON optionData));
in pkgs.runCommand "aurora-documentation" {
  nativeBuildInputs = [ pkgs.python3 pkgs.diffutils ];
  passthru = { inherit optionData; };
} ''
  mkdir -p "$out/share/doc/aurora"
  cp ${optionsFile} "$out/share/doc/aurora/options.json"
  python3 ${../scripts/render-options.py} ${optionsFile} > "$out/share/doc/aurora/options.md"
  diff -u ${../docs/options.md} "$out/share/doc/aurora/options.md"
''
