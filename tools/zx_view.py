#!/usr/bin/env python3
"""View ZX Spectrum graphics data from the unpacked memory image.

Subcommands:
  screen FILE ORG ADDR OUT.png        render a 6912-byte SCR at ADDR
  bitmap FILE ORG ADDR OUT.png [--width BYTES] [--height ROWS] [--zoom N]
                                      render raw linear 1bpp data
  sheet  FILE ORG ADDR OUT.png --w BYTES --h ROWS --count N [--cols C]
                                      grid of consecutive W*H cells
Numbers accept decimal or 0x hex.
"""
import sys
from PIL import Image

PALETTE = [
    (0, 0, 0), (0, 0, 215), (215, 0, 0), (215, 0, 215),
    (0, 215, 0), (0, 215, 215), (215, 215, 0), (215, 215, 215),
]
BRIGHT = [
    (0, 0, 0), (0, 0, 255), (255, 0, 0), (255, 0, 255),
    (0, 255, 0), (0, 255, 255), (255, 255, 0), (255, 255, 255),
]


def num(s):
    return int(s, 16) if s.lower().startswith("0x") else int(s)


def zx_screen(mem, base, addr):
    img = Image.new("RGB", (256, 192))
    px = img.load()
    off = addr - base
    for y in range(192):
        third = y >> 6
        row = (y >> 3) & 7
        line = y & 7
        src = off + third * 2048 + line * 256 + row * 32
        attr_off = off + 6144 + (y >> 3) * 32
        for xb in range(32):
            b = mem[src + xb]
            attr = mem[attr_off + xb]
            ink = attr & 7
            paper = (attr >> 3) & 7
            pal = BRIGHT if attr & 0x40 else PALETTE
            for bit in range(8):
                on = (b >> (7 - bit)) & 1
                px[xb * 8 + bit, y] = pal[ink] if on else pal[paper]
    return img


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    mem = open(sys.argv[2], "rb").read()
    base = num(sys.argv[3])
    addr = num(sys.argv[4])
    out = sys.argv[5]
    args = sys.argv[6:]

    def opt(name, default):
        if name in args:
            return num(args[args.index(name) + 1])
        return default

    if cmd == "screen":
        img = zx_screen(mem, base, addr)
        img = img.resize((512, 384), Image.NEAREST)
        img.save(out)
    elif cmd == "bitmap":
        w = opt("--width", 32)
        h = opt("--height", 192)
        zoom = opt("--zoom", 2)
        img = Image.new("1", (w * 8, h))
        px = img.load()
        off = addr - base
        for y in range(h):
            for xb in range(w):
                i = off + y * w + xb
                if i >= len(mem):
                    break
                b = mem[i]
                for bit in range(8):
                    px[xb * 8 + bit, y] = (b >> (7 - bit)) & 1
        img = img.resize((w * 8 * zoom, h * zoom), Image.NEAREST)
        img.save(out)
    elif cmd == "sheet":
        w = opt("--w", 2)
        h = opt("--h", 16)
        count = opt("--count", 64)
        cols = opt("--cols", 16)
        zoom = opt("--zoom", 3)
        rows = (count + cols - 1) // cols
        img = Image.new("RGB", (cols * (w * 8 + 2), rows * (h + 2)), (60, 60, 90))
        off = addr - base
        for n in range(count):
            cell = Image.new("1", (w * 8, h))
            px = cell.load()
            for y in range(h):
                for xb in range(w):
                    i = off + n * w * h + y * w + xb
                    if i >= len(mem):
                        break
                    b = mem[i]
                    for bit in range(8):
                        px[xb * 8 + bit, y] = (b >> (7 - bit)) & 1
            img.paste(cell.convert("RGB"), ((n % cols) * (w * 8 + 2) + 1,
                                            (n // cols) * (h + 2) + 1))
        img = img.resize((img.width * zoom, img.height * zoom), Image.NEAREST)
        img.save(out)
    else:
        print(__doc__)
        return 1
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
