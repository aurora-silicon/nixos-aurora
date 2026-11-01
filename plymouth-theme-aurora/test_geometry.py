#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise the installed helper with synthetic DT cells, without hardware.

Also supplies reproducible platform fixtures to render/render.sh:
  test_geometry.py --fixture DIR WIDTH PANEL_HEIGHT NOTCH [--full] [--omit-notch]
"""
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def fixture(root, width, height, notch, full=False, omit_notch=False):
    root = Path(root)
    def prop(name, data):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    def cell(name, value):
        prop(name, struct.pack(">I", value))
    for parent in ("", "chosen/", "reserved-memory/"):
        cell(parent + "#address-cells", 2)
        cell(parent + "#size-cells", 2)
    prop("reserved-memory/ranges", b"")
    stride = width * 4
    crop = 0 if full else notch
    base = 0x10000000000
    fb = "chosen/framebuffer@10000000000/"
    prop(fb + "compatible", b"apple,simple-framebuffer\0simple-framebuffer\0")
    prop(fb + "reg", struct.pack(">QQ", base + crop * stride, stride * (height - crop)))
    cell(fb + "width", width)
    cell(fb + "height", height - crop)
    cell(fb + "stride", stride)
    region = "reserved-memory/framebuffer@10000000000/"
    prop(region + "compatible", b"framebuffer\0")
    prop(region + "reg", struct.pack(">QQ", base, stride * height * 2))
    prop("aliases/dcp", b"/soc/dcp@0\0")
    if not omit_notch and notch:
        cell("soc/dcp@0/apple,notch-height", notch)
    return root


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dt = self.root / "dt"
        self.out = self.root / "run/aurora.script"

    def tearDown(self):
        self.tmp.cleanup()

    def generate(self):
        subprocess.run(["sh", str(THEME / "aurora-plymouth"), str(THEME),
                        str(self.out), str(self.dt)], check=True)
        text = self.out.read_text()
        values = tuple(map(int, re.findall(r"aurora_(?:panel_width|panel_height|notch_height) = (\d+);", text)))
        self.assertTrue(text.endswith((THEME / "aurora.script").read_text()))
        return values

    def test_platforms_both_origins(self):
        for w, h, n in ((3456, 2234, 74), (2560, 1664, 64), (2408, 1506, 0), (2560, 1665, 65)):
            for full in (False, True):
                with self.subTest(width=w, height=h, notch=n, full=full):
                    shutil.rmtree(self.dt, ignore_errors=True)
                    fixture(self.dt, w, h, n, full)
                    self.assertEqual(self.generate(), (w, h, n))

    def test_missing_dcp_property_uses_framebuffer_origin(self):
        fixture(self.dt, 3456, 2234, 74, omit_notch=True)
        self.assertEqual(self.generate(), (3456, 2234, 74))

    def test_stale_dcp_property_uses_framebuffer_origin(self):
        fixture(self.dt, 3456, 2234, 74)
        (self.dt / "soc/dcp@0/apple,notch-height").write_bytes(struct.pack(">I", 16))
        self.assertEqual(self.generate(), (3456, 2234, 74))

    def test_absent_tree_clears_previous_boot_data(self):
        fixture(self.dt, 3456, 2234, 74)
        self.generate()
        shutil.rmtree(self.dt)
        self.assertEqual(self.generate(), (0, 0, 0))

    def test_truncated_cell_disables_correction(self):
        fixture(self.dt, 2560, 1664, 64)
        next((self.dt / "chosen").glob("framebuffer*/height")).write_bytes(b"\0\0")
        self.assertEqual(self.generate(), (0, 0, 0))

    def test_ambiguous_framebuffers_disable_correction(self):
        fixture(self.dt, 2560, 1664, 64)
        shutil.copytree(next((self.dt / "chosen").glob("framebuffer*")), self.dt / "chosen/framebuffer@2")
        self.assertEqual(self.generate(), (0, 0, 0))

    def test_non_row_aligned_origin_disables_correction(self):
        fixture(self.dt, 2560, 1664, 64)
        reg = next((self.dt / "chosen").glob("framebuffer*/reg"))
        base, size = struct.unpack(">QQ", reg.read_bytes())
        reg.write_bytes(struct.pack(">QQ", base + 1, size))
        self.assertEqual(self.generate(), (0, 0, 0))

    def test_missing_reservation_disables_correction(self):
        fixture(self.dt, 2560, 1664, 64)
        shutil.rmtree(self.dt / "reserved-memory")
        self.assertEqual(self.generate(), (0, 0, 0))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fixture":
        fixture(sys.argv[2], *map(int, sys.argv[3:6]), full="--full" in sys.argv,
                omit_notch="--omit-notch" in sys.argv)
    else:
        THEME = Path(sys.argv.pop(1) if len(sys.argv) > 1 else __file__).resolve()
        if THEME.is_file():
            THEME = THEME.parent
        unittest.main()
