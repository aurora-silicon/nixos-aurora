"""The PipeWire daemon carries the patches Fedora and ALARM carry."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCHES = [
    '1000-module-raop-match-an-RTSP-reply-without-CSeq-to-the-.patch',
    '1001-module-raop-sink-say-why-a-receiver-session-was-drop.patch',
    '1002-module-raop-sink-default-sess.latency.msec-to-whole-.patch',
    '1003-module-raop-discover-reload-a-sink-that-unloaded-its.patch',
    '1004-module-raop-sink-give-up-on-a-session-that-never-rea.patch',
    '1005-filter-graph-follow-plugin-latency-after-activation.patch',
    '1006-filter-graph-keep-the-software-volume-at-unity-on-ev.patch',
]


class PipeWireTests(unittest.TestCase):
    def test_overlay_applies_every_patch_in_order(self):
        overlay = (ROOT / 'overlay.nix').read_text()
        block = re.search(r'^  aurora-pipewire = prev\.pipewire\.overrideAttrs \(old: \{\n(.*?)^  \}\);',
                          overlay, re.M | re.S)
        self.assertIsNotNone(block)
        listed = re.findall(r'\./patches/pipewire/(\S+\.patch)', block[1])
        self.assertEqual(listed, PATCHES)
        self.assertEqual(sorted(p.name for p in (ROOT / 'patches/pipewire').glob('*.patch')), PATCHES)
        self.assertIn('(old.patches or [ ]) ++ map stableFile [', block[1])
        self.assertIn('doCheck = true;', block[1])
        # Clients keep nixpkgs' PipeWire; only the daemon is replaced.
        self.assertNotRegex(overlay, re.compile(r'^  pipewire = ', re.M))

    def test_daemon_uses_it_and_ci_builds_it(self):
        audio = (ROOT / 'modules/audio.nix').read_text()
        self.assertIn('services.pipewire.package = lib.mkDefault pkgs.aurora-pipewire;', audio)
        self.assertRegex(audio, re.compile(r'pipewireFixes = lib\.mkOption \{\n\s+type = lib\.types\.bool;\n\s+default = true;'))
        flake = (ROOT / 'flake.nix').read_text()
        self.assertIn('pipewire = pkgs.aurora-pipewire;', flake)
        self.assertIn('-1006-filter-graph-keep-the-software-volume-at-unity-on-ev.patch', flake)


if __name__ == '__main__':
    unittest.main()
