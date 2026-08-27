#!/usr/bin/env python3
"""Render a zone from the editable resources - the reference model for
what src/list.mac and src/zone.mac do on the UKNC.

    python3 tools/zone_render.py 0 tmp/zone000.png [--uknc] [--zoom 2]
    python3 tools/zone_render.py sheet tmp/zones.png [--uknc]

The display-list interpreter here is byte-for-byte the same machine as
the one in the game image (tools/resources.py assembles the byte code);
`--uknc` additionally applies the port's colour reduction: three inks
plus black per 8-line cell row, chosen by pixel count.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resources as R

ROWS, COLS = 24, 32
ZONE_ROWS = 22          # rows 22..23 are the HUD

ZXRGB = [(0, 0, 0), (0, 0, 205), (205, 0, 0), (205, 0, 205),
         (0, 205, 0), (0, 205, 205), (205, 205, 0), (205, 205, 205),
         (0, 0, 0), (0, 0, 255), (255, 0, 0), (255, 0, 255),
         (0, 255, 0), (0, 255, 255), (255, 255, 0), (255, 255, 255)]


class Cells:
    """The zone as the UKNC engine keeps it: per cell a tile index, an
    ink 0..15 and the collision class."""

    def __init__(self):
        self.tile = [[None] * COLS for _ in range(ROWS)]
        self.ink = [[0] * COLS for _ in range(ROWS)]
        self.solid = [[0] * COLS for _ in range(ROWS)]
        self.hit = [[0] * COLS for _ in range(ROWS)]

    def plot(self, row, col, tile, ink, solid, hit):
        if 0 <= row < ROWS and 0 <= col < COLS:
            self.tile[row][col] = tile
            self.ink[row][col] = ink
            self.solid[row][col] = solid
            self.hit[row][col] = hit


def run_list(lists, lid, cells, row, col, ink=7, base=0, solid=1, hit=0,
             depth=0):
    """Interpret one display list.  Mirrors the original at 0xAF2B."""
    d, e = row, col
    stack = []
    ops = lists[lid]
    i = 0
    while i < len(ops):
        op = ops[i]
        k = op[0]
        i += 1
        if k == "tile":
            if not (e & 0x20):
                cells.plot(d, e, base + op[1], ink, solid, hit)
            e = (e + 1) & 0xFF
        elif k == "move":
            d = (d + op[1]) & 0xFF
            e = (e + op[2]) & 0xFF
        elif k == "nl":
            d = (d + 1) & 0xFF
            e = (e + op[1]) & 0xFF
        elif k == "ink":
            ink = op[1]
        elif k == "at":
            d, e = op[1], op[2]
        elif k == "attr":
            ink = (op[1] & 7) | (8 if op[1] & 0x40 else 0)
        elif k == "rep":
            stack.append([op[1], i])
        elif k == "endrep":
            stack[-1][0] -= 1
            if stack[-1][0]:
                i = stack[-1][1]
            else:
                stack.pop()
        elif k == "call":
            if depth < 8:
                run_list(lists, op[1], cells, d, e, ink, base, solid, hit,
                         depth + 1)
        elif k == "hrun":
            for _ in range(op[1]):
                if not (e & 0x20):
                    cells.plot(d, e, base + op[2], ink, solid, hit)
                e = (e + 1) & 0xFF
        elif k == "vrun":
            for _ in range(op[1]):
                if not (e & 0x20):
                    cells.plot(d, e, base + op[2], ink, solid, hit)
                d = (d + 1) & 0xFF
        elif k == "base":
            base = op[1]
        elif k == "solid":
            solid = op[1]
        elif k == "anim":
            pass                    # runtime hook: nothing on a still frame
        elif k == "hit":
            hit = op[1]
        elif k == "end":
            return
    return


def render_zone(zone, lists=None, zones=None):
    lists = lists if lists is not None else R.read_lists()
    zones = zones if zones is not None else R.read_zones()
    cells = Cells()
    for row, col, obj in zones[zone]:
        run_list(lists, obj, cells, row, col, ink=7, base=0, solid=1, hit=0)
    return cells


def row_palettes(cells, tiles, ninks=3):
    """The port's colour reduction: per 8-line cell row pick the `ninks`
    most-used inks; every other ink snaps to the nearest survivor.
    -> (palette per row, ink slot per cell)."""
    pals, slots = [], [[0] * COLS for _ in range(ROWS)]
    for r in range(ROWS):
        weight = Counter()
        for c in range(COLS):
            t = cells.tile[r][c]
            if t is None:
                continue
            n = sum(bin(b).count("1") for b in tiles[t])
            if n:
                weight[cells.ink[r][c]] += n
        pal = [i for i, _ in weight.most_common(ninks)]
        while len(pal) < ninks:
            pal.append(7)
        pals.append(pal)
        for c in range(COLS):
            ink = cells.ink[r][c]
            if ink in pal:
                slots[r][c] = pal.index(ink) + 1
            else:
                tr = ZXRGB[ink]
                best = min(range(ninks), key=lambda k: sum(
                    (a - b) ** 2 for a, b in zip(ZXRGB[pal[k]], tr)))
                slots[r][c] = best + 1
    return pals, slots


def to_image(cells, tiles, uknc=False, zoom=2):
    from PIL import Image
    img = Image.new("RGB", (COLS * 8, ROWS * 8))
    px = img.load()
    pals, slots = row_palettes(cells, tiles) if uknc else (None, None)
    for r in range(ROWS):
        for c in range(COLS):
            t = cells.tile[r][c]
            if t is None:
                continue
            if uknc:
                col = ZXRGB[pals[r][slots[r][c] - 1]]
            else:
                col = ZXRGB[cells.ink[r][c]]
            g = tiles[t]
            for y in range(8):
                b = g[y]
                for x in range(8):
                    if b & (0x80 >> x):
                        px[c * 8 + x, r * 8 + y] = col
    if zoom != 1:
        img = img.resize((img.width * zoom, img.height * zoom), Image.NEAREST)
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("what", help="zone number, or 'sheet'")
    ap.add_argument("out")
    ap.add_argument("--uknc", action="store_true")
    ap.add_argument("--zoom", type=int, default=2)
    a = ap.parse_args()
    tiles, lists, zones = R.read_tiles(), R.read_lists(), R.read_zones()
    if a.what == "sheet":
        from PIL import Image
        cols = 5
        rows = (len(zones) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * COLS * 8, rows * ROWS * 8))
        for z in range(len(zones)):
            im = to_image(render_zone(z, lists, zones), tiles, a.uknc, 1)
            sheet.paste(im, ((z % cols) * COLS * 8, (z // cols) * ROWS * 8))
        sheet.save(a.out)
    else:
        im = to_image(render_zone(int(a.what), lists, zones), tiles,
                      a.uknc, a.zoom)
        im.save(a.out)
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
