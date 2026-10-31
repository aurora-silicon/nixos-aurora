{ lib, clangStdenv, gnustep-base, gnustep-make, gnustep-libobjc, python3, gitMinimal, src, baseSrc, basePatch, version }:
let
  # Base 1.29 in nixpkgs lacks NSData URL options and sorted JSON keys.
  # Keep this newer Foundation private to the compiler, with the same source
  # and upstream fix as Fedora/ALARM. The system GNUstep package is untouched.
  compilerBase = gnustep-base.overrideAttrs (old: {
    pname = "mil-hwx-gnustep-base";
    version = "1.31.1";
    src = baseSrc;
    patches = [ basePatch ];
    # Only the makefile installation adjustment from nixpkgs is needed for
    # this CLI dependency. Its older desktop search-path patch does not apply
    # to 1.31; the compiler never uses GNUstep application/bundle discovery.
    postPatch = (old.postPatch or "") + ''
      substituteInPlace Makefile.postamble \
        --replace-fail '$(DESTDIR)$(GNUSTEP_MAKEFILES)' '$(DESTDIR_GNUSTEP_MAKEFILES)'
    '';
    configureFlags = (old.configureFlags or [ ]) ++ [
      "--disable-tls" "--disable-xslt" "--disable-zeroconf"
      "--disable-libdispatch" "--disable-nsurlsession"
    ];
  });
in
clangStdenv.mkDerivation {
  pname = "mil-hwx-compiler";
  inherit src version;
  strictDeps = true;
  nativeBuildInputs = [ gnustep-make python3 ];
  buildInputs = [ compilerBase gnustep-libobjc ];
  dontConfigure = true;
  # The compiler uses Foundation and ARC, not Apple's frameworks. nixpkgs'
  # GNUstep runtime/make packages already use libobjc2; no online bootstrap is permitted.
  makeFlags = [
    "GNUSTEP_PREFIX=${gnustep-make}"
    "GNUSTEP_CONFIG=${gnustep-make}/bin/gnustep-config"
    "CXX=clang++"
  ];
  buildFlags = [ "build/mil-hwxc" ];
  doCheck = true;
  nativeCheckInputs = [ gitMinimal ];
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
