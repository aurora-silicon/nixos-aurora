"""FFmpeg and gst-plugins-good carry the V4L2 ProRes patches Fedora and ALARM carry."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = [
    '0001-avcodec-v4l2_buffers-use-the-driver-s-strides-for-si.patch',
    '0002-avcodec-v4l2_context-pick-the-raw-V4L2-format-the-dr.patch',
    '0003-avcodec-v4l2_m2m-add-ProRes-decoder-and-encoder.patch',
]
GST = ['0001-v4l2-add-ProRes-decoder-and-encoder.patch',
       '0002-v4l2videodec-switch-to-a-supported-capture-format-be.patch']


def block(overlay, name, base):
    match = re.search(rf'^  {name} = {re.escape(base)}\.overrideAttrs \(old: \{{\n(.*?)^  \}}\);', overlay, re.M | re.S)
    return match[1] if match else None


class ProResV4l2Tests(unittest.TestCase):
    def test_overlay_applies_every_patch_in_order(self):
        overlay = (ROOT / 'overlay.nix').read_text()
        for name, base, directory, patches in (
                ('aurora-ffmpeg', 'prev.ffmpeg', 'ffmpeg', FFMPEG),
                ('aurora-gst-plugins-good', 'prev.gst_all_1.gst-plugins-good', 'gst-plugins-good', GST)):
            with self.subTest(attribute=name):
                body = block(overlay, name, base)
                self.assertIsNotNone(body)
                self.assertEqual(re.findall(rf'\./patches/{directory}/(\S+\.patch)', body), patches)
                self.assertEqual(sorted(p.name for p in (ROOT / 'patches' / directory).glob('*.patch')), patches)
                self.assertIn('(old.patches or [ ]) ++', body)
        self.assertIn("#define CONFIG_PRORES_V4L2M2M_ENCODER 1", block(overlay, 'aurora-ffmpeg', 'prev.ffmpeg'))
        # Separate attributes: everything else keeps nixpkgs' cached builds.
        self.assertNotRegex(overlay, re.compile(r'^  (ffmpeg|gst_all_1) = ', re.M))

    def test_ci_builds_both(self):
        flake = (ROOT / 'flake.nix').read_text()
        self.assertIn('ffmpeg = pkgs.aurora-ffmpeg;', flake)
        self.assertIn('gst-plugins-good = pkgs.aurora-gst-plugins-good;', flake)
        checks = (ROOT / 'checks/package-overrides.nix').read_text()
        self.assertIn('pkgs.aurora-ffmpeg.version == "9.0.2"', checks)

    def test_installed_systems_get_both(self):
        video = (ROOT / 'modules/video.nix').read_text()
        self.assertRegex(video, re.compile(r'proresV4l2 = lib\.mkOption \{\n\s+type = lib\.types\.bool;\n\s+default = true;'))
        self.assertIn('environment.systemPackages = [ pkgs.aurora-ffmpeg ];', video)
        # GStreamer scans GST_PLUGIN_PATH_1_0 before GST_PLUGIN_SYSTEM_PATH_1_0,
        # which nixpkgs' wrappers prefix with the application's own plugins.
        self.assertIn('environment.sessionVariables.GST_PLUGIN_PATH_1_0 = [ "${proresGstPlugin}/lib/gstreamer-1.0" ];', video)
        self.assertNotIn('GST_PLUGIN_SYSTEM_PATH', video.split('config = ')[1])
        self.assertIn('${pkgs.aurora-gst-plugins-good}/lib/gstreamer-1.0/libgstvideo4linux2.so', video)
        self.assertIn('./video.nix', (ROOT / 'modules/aurora.nix').read_text())
        composition = (ROOT / 'checks/module-composition.nix').read_text()
        self.assertIn('aurora.video.proresV4l2 = false;', composition)
        self.assertIn('-aurora-gst-video4linux2/lib/gstreamer-1.0', composition)
        workflow = (ROOT / '.github/workflows/checks.yml').read_text()
        self.assertIn('.#checks.aarch64-linux.module-composition', workflow)


if __name__ == '__main__':
    unittest.main()
