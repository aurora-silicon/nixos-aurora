# credentialsd: the credential manager behind xdg-desktop-portal's
# experimental Credential portal. Browsers that use the portal (Firefox with
# the credential portal backend) reach USB/NFC security keys, phones over
# hybrid and platform passkey providers through it; aurora-fido's Secure
# Enclave agent is one such provider (modules/fido.nix).
{ lib
, stdenv
, src
, pin
, rustPlatform
, cargo
, rustc
, meson
, ninja
, pkg-config
, blueprint-compiler
, desktop-file-utils
, appstream
, libxml2
, glib
, gtk4
, dbus
, libnfc
, pcsclite
, openssl
, systemd
, publicsuffix-list
, gettext
, python3
, wrapGAppsHook4
, rustPlatformBindgenHook ? rustPlatform.bindgenHook
}:

stdenv.mkDerivation {
  pname = "credentialsd";
  inherit (pin) version;
  inherit src;

  # credentialsd main after 0.4.0 (0001) and the platform passkey provider
  # series (0002-0006): drop-in discovery in share/credentialsd/providers,
  # the internal transport, password and locked states, and
  # GetClientCapabilities() for the portal.
  patches = [
    ../patches/credentialsd/0001-backport-main-v0.4.0..ca77b3e.patch
    ../patches/credentialsd/0002-ui-Add-password-and-locked-states-for-platform-provi.patch
    ../patches/credentialsd/0003-daemon-Discover-platform-passkey-providers.patch
    ../patches/credentialsd/0004-daemon-Route-requests-to-platform-passkey-providers.patch
    ../patches/credentialsd/0005-daemon-Report-client-capabilities-to-the-portal.patch
    ../patches/credentialsd/0006-doc-Document-the-platform-provider-API.patch
  ];

  # Cargo.lock as patched (the series adds no crate, only dependency edges).
  cargoDeps = rustPlatform.importCargoLock { lockFile = ../locks/credentialsd.Cargo.lock; };

  postPatch = ''
    cmp Cargo.lock ${../locks/credentialsd.Cargo.lock}
    # libwebauthn reads the Public Suffix List from /usr/share/publicsuffix;
    # NixOS has it in the publicsuffix-list package.
    substituteInPlace "$cargoDepsCopy"/libwebauthn-0.11.0/src/ops/webauthn/psl/dat.rs \
      --replace-fail '"/usr/share/publicsuffix/public_suffix_list.dat"' \
                     '"${publicsuffix-list}/share/publicsuffix/public_suffix_list.dat"'

    # systemd user units go to $out/lib/systemd/user (the build uses $prefix/lib).
    grep -q "prefix / 'lib' / 'systemd' / 'user'" systemd/meson.build
    patchShebangs credentialsd-ui/data/resources/icons/copy-icons.py
  '';

  nativeBuildInputs = [
    meson
    ninja
    pkg-config
    cargo
    rustc
    rustPlatform.cargoSetupHook
    rustPlatformBindgenHook
    blueprint-compiler
    desktop-file-utils
    appstream
    libxml2
    glib
    gettext
    python3
    wrapGAppsHook4
  ];

  buildInputs = [ glib gtk4 dbus libnfc pcsclite openssl systemd ];

  mesonFlags = [
    "-Dprofile=release"
    "-Dcargo_locked=true"
    "-Dcargo_offline=true"
    "-Dfeature_web_extension=disabled"
    "-Dfeature_demo_client=disabled"
  ];

  # Unit tests of the three crates, the D-Bus integration test (own bus),
  # gschema and appdata validation.
  doCheck = true;
  nativeCheckInputs = [ dbus ];
  mesonCheckFlags = [ "--timeout-multiplier" "0" ];

  postInstall = ''
    grep -qx 'Interfaces=org.freedesktop.impl.portal.experimental.Credential' \
      $out/share/xdg-desktop-portal/portals/credentialsd.portal
    mkdir -p $out/share/credentialsd/providers
  '';

  passthru.commit = pin.commit;

  meta = {
    description = "Credential manager for WebAuthn passkeys and security keys, with platform passkey providers";
    homepage = "https://github.com/linux-credentials/credentialsd";
    license = lib.licenses.lgpl3Only;
    platforms = [ "aarch64-linux" ];
    mainProgram = "credentialsd";
  };
}
