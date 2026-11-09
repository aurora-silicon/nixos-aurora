{ pkgs }:
let
  # Changing the caller's compiler must reach the shared build settings,
  # including for the two-stage build's shader tools.
  llvmPackages = pkgs.llvmPackages_22;
  mesa = pkgs.mesa.override { inherit llvmPackages; };
  compilerSelected = builtins.elem "export CC=${llvmPackages.clang}/bin/clang"
    (pkgs.lib.splitString "\n" mesa.preConfigure);
  fexWithoutQt = pkgs.fex.override { withQt = false; };
  proton = pkgs.aurora-proton.override { inherit llvmPackages; };
in
assert pkgs.lib.assertMsg
  (builtins.all (tool: builtins.elem (pkgs.lib.getDev tool) proton.patchedNtdll.nativeBuildInputs)
    [ llvmPackages.clang-unwrapped llvmPackages.lld llvmPackages.llvm ])
  "Aurora Proton must use the caller's complete LLVM toolchain";
assert pkgs.lib.assertMsg
  (builtins.elem (pkgs.lib.cmakeBool "BUILD_FEXCONFIG" false) fexWithoutQt.cmakeFlags)
  "Aurora FEX must preserve the upstream withQt override";
assert pkgs.lib.assertMsg compilerSelected
  "Aurora Mesa must honor the caller's llvmPackages override";
pkgs.runCommand "aurora-package-overrides" { } "touch $out"
