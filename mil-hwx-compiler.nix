{ lib, clangStdenv, gnustep-base, gnustep-make, gnustep-libobjc, python3, src, version }:
clangStdenv.mkDerivation {
  pname = "mil-hwx-compiler";
  inherit src version;
  strictDeps = true;
  nativeBuildInputs = [ gnustep-make python3 ];
  buildInputs = [ gnustep-base gnustep-libobjc ];
  dontConfigure = true;
  # The compiler uses Foundation and ARC, not Apple's frameworks. nixpkgs'
  # GNUstep packages already use libobjc2; no online bootstrap is permitted.
  makeFlags = [
    "GNUSTEP_PREFIX=${gnustep-make}"
    "GNUSTEP_CONFIG=${gnustep-make}/bin/gnustep-config"
    "CXX=clang++"
  ];
  buildFlags = [ "build/mil-hwxc" ];
  doCheck = true;
  checkTarget = "test-h13";
  postCheck = "python3 tests/test_h14_fixture_programs.py build/mil-hwxc";
  installPhase = ''
    runHook preInstall
    install -Dm755 build/mil-hwxc "$out/bin/mil-hwxc"
    install -Dm644 LICENSE "$out/share/licenses/mil-hwx-compiler/LICENSE"
    runHook postInstall
  '';
  meta = {
    description = "Open MIL to ANE HWX and ANEC compiler";
    homepage = "https://github.com/joshuaswarren/mil-hwx-compiler";
    license = lib.licenses.mit;
    platforms = [ "aarch64-linux" ];
    mainProgram = "mil-hwxc";
  };
}
