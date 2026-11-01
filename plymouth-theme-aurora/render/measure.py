#!/usr/bin/env python3
"""measure.py logo128.png logo256.png render.rgb W H: find the Aurora logo in a rendered
frame (raw RGB) and report its size, top-left and how many sampled pixels match aura's image."""
import struct, sys, zlib
def png_rgb(p):
    d = open(p, 'rb').read(); i = 8; idat = b''
    while i < len(d):
        n, t = struct.unpack('>I4s', d[i:i+8]); c = d[i+8:i+8+n]; i += 12 + n
        if t == b'IHDR': w, h, bd, ct = struct.unpack('>IIBB', c[:10])
        elif t == b'IDAT': idat += c
    bpp = 3 if ct == 2 else 4
    raw = zlib.decompress(idat); out = []; prev = bytearray(w * bpp); o = 0
    for y in range(h):
        f = raw[o]; line = bytearray(raw[o+1:o+1+w*bpp]); o += 1 + w*bpp
        for x in range(len(line)):
            a = line[x-bpp] if x >= bpp else 0; b = prev[x]; cc = prev[x-bpp] if x >= bpp else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + b) & 255
            elif f == 3: line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(b - cc), abs(a - cc), abs(a + b - 2*cc)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else cc)) & 255
        out.append([tuple(line[x*bpp:x*bpp+3]) for x in range(w)]); prev = line
    return w, h, out
def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logo128")
    parser.add_argument("logo256")
    parser.add_argument("frame")
    parser.add_argument("width", type=int)
    parser.add_argument("height", type=int)
    parser.add_argument("--panel", nargs=3, type=int, metavar=("WIDTH", "HEIGHT", "NOTCH"))
    parser.add_argument("--size", type=int, choices=(128, 256), default=256)
    args = parser.parse_args()
    logos = [png_rgb(args.logo128), png_rgb(args.logo256)]
    raw = open(args.frame, "rb").read()
    W, H = args.width, args.height
    assert len(raw) == W * H * 3, "incomplete render capture"

    def score(logo, x0, y0, step=16):
        lw, lh, img = logo
        matched = total = 0
        for y in range(0, lh, step):
            for x in range(0, lw, step):
                total += 1
                if 0 <= x0+x < W and 0 <= y0+y < H:
                    o = 3 * ((y0+y) * W + x0+x)
                    matched += raw[o:o+3] == bytes(img[y][x])
        return matched / total

    # Locate independently of the expected physical rectangle, then verify
    # every pixel. This catches a wrong origin, size, or raster scale.
    radius = max(128, args.panel[2] + 4 if args.panel else 0)
    best = (0, 0, 0, 0)
    for logo in logos:
        lw = logo[0]
        cx, cy = (W-lw)//2, (H-lw)//2
        for dy in range(-radius, radius+1):
            value = score(logo, cx, cy+dy)
            if value > best[0]:
                best = value, lw, cx, cy+dy
    _, size, x, y = best
    logo = next(l for l in logos if l[0] == size)
    exact = score(logo, x, y, step=1)
    result = {"frame": args.frame, "mode": [W, H], "rect": [x, y, size, size],
              "exact_pixels": exact == 1.0, "match_percent": 100 * exact}
    if args.panel:
        pw, ph, notch = args.panel
        origin = notch if notch and W == pw and H == ph-notch else 0
        if W == pw and H in (ph, ph-notch):
            expected = [(pw-args.size)//2, (ph-args.size)//2, args.size, args.size]
        else:
            expected = [(W-args.size)//2, (H-args.size)//2, args.size, args.size]
        physical = [x, y+origin, size, size]
        result.update(panel=args.panel, physical_rect=physical, aura_rect=expected)
        passed = physical == expected and exact == 1.0
    else:
        passed = exact == 1.0
    import json
    print(json.dumps(result, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
