#!/usr/bin/env python3
"""exolon_re.py - reverse-engineering library for the ZX Spectrum EXOLON.

Everything the extractors need to read the original game out of the tape:
the 48K memory image, the display-list ("picture program") interpreter that
the original uses to paint zone scenery, and the zone tables.

The original draws every piece of scenery with a tiny byte-code language
interpreted at 0xAF2B.  A program is a stream of opcodes over a cursor
(D = cell row, E = cell column) and a current attribute byte C:

    00..60   draw tile A at (D,E) from the current tile base, E += 1
    61..8F   D += op-0x78; E += next byte          (relative cursor move)
    90..CE   D += 1; E += op-0xAF                  (newline + column delta)
    CF..DE   ink = op-0xCF (>=8 -> bright), keep paper bits of C
    DF a b   cursor D=a, E=b
    E0 a     attribute C = a
    E1 n     push repeat count n / start of block
    E2       end of block (repeat n times)
    E3 lo hi call sub-program
    E4 n t   draw tile t n times to the right
    E5 n t   draw tile t n times downwards
    E6 lo hi set tile graphics base
    E7       draw tile 0x20 from base 0xD7E0, E += 1
    E8 n     value written into the "solid map" for every drawn cell
    E9 / EA  value written into the "hit map" for every drawn cell (0 / FF)
    EB n     (self-modifying hook used by the animated tiles; ignored here)
    other    end of program

`BIT 5,E; RET NZ` at the tile plotter drops any cell whose column is not
0..31, which is how objects hang off the right edge; columns are taken
modulo 256 and the ones outside 0..31 are simply not drawn.

Zone layout: a 125-entry pointer table at 0xC7F4; each zone is a list of
{row, col, object} triples ended by 0xFF.  Object graphics are 62 display
lists indexed through the table at 0x852E.  A second table at 0x94C6 gives
each object's bounding box (5 bytes: object, dx, w, dy, h).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- tape layout ---------------------------------------------------------
TAPE = ROOT / "EXOLON.TAP"
MAIN_BLOCK = 7          # tap block index of the main game image
MAIN_ORG = 0x6D60       # where the custom loader puts it (up to 0xFFFF)

# --- game tables ---------------------------------------------------------
ZONE_PTRS = 0xC7F4
ZONE_COUNT = 125
ZONE_DATA_END = 0xD8E0
OBJ_PTRS = 0x852E
OBJ_COUNT = 62
OBJ_BOXES = 0x94C6
DRAW_LIST = 0xAF2B      # the interpreter itself
SPECIAL_BASE = 0xD7E0   # base used by opcode E7

SCR_ROWS = 24
SCR_COLS = 32


# ------------------------------------------------------------------ tape --
def tap_blocks(path=TAPE):
    """Yield the raw data bytes of every .TAP block (flag and checksum
    stripped)."""
    data = Path(path).read_bytes()
    off = 0
    while off + 2 <= len(data):
        blen = data[off] | (data[off + 1] << 8)
        off += 2
        yield data[off + 1:off + blen - 1]
        off += blen


def load_image(path=TAPE):
    """Build the 64K memory image the game runs in (RAM only, ROM zeroed)."""
    blocks = list(tap_blocks(path))
    mem = bytearray(0x10000)
    body = blocks[MAIN_BLOCK]
    mem[MAIN_ORG:MAIN_ORG + len(body)] = body
    return mem


# ------------------------------------------------------- picture programs --
class Screen:
    """A ZX Spectrum screen as the game builds it: 8x8 cells of 1bpp pixels,
    one attribute per cell, plus the two shadow maps the tile plotter keeps
    (solid map at 0x6100, hit map at 0x5B00)."""

    def __init__(self):
        self.pix = [[bytearray(8) for _ in range(SCR_COLS)]
                    for _ in range(SCR_ROWS)]
        self.attr = [[0] * SCR_COLS for _ in range(SCR_ROWS)]
        self.solid = [[0] * SCR_COLS for _ in range(SCR_ROWS)]
        self.hit = [[0] * SCR_COLS for _ in range(SCR_ROWS)]
        self.used = [[False] * SCR_COLS for _ in range(SCR_ROWS)]

    def plot(self, row, col, glyph, attr, solid, hit):
        if not (0 <= row < SCR_ROWS) or not (0 <= col < SCR_COLS):
            return
        self.pix[row][col] = bytearray(glyph)
        self.attr[row][col] = attr
        self.solid[row][col] = solid
        self.hit[row][col] = hit
        self.used[row][col] = True


class ListRunner:
    """Interpreter for the scenery display lists."""

    def __init__(self, mem):
        self.mem = mem

    def run(self, addr, screen, row=0, col=0, attr=0x07,
            base=0, solid=0, hit=0, depth=0):
        mem = self.mem
        d, e, c = row, col, attr
        stack = []
        while True:
            op = mem[addr]
            addr += 1
            if op < 0x61:
                self._tile(screen, d, e, op, base, c, solid, hit)
                e = (e + 1) & 0xFF
            elif op < 0x90:
                d = (d + op - 0x78) & 0xFF
                e = (e + mem[addr]) & 0xFF
                addr += 1
            elif op < 0xCF:
                d = (d + 1) & 0xFF
                e = (e + op - 0xAF) & 0xFF
            elif op < 0xDF:
                ink = op - 0xCF
                if ink >= 8:
                    ink = (ink - 8) | 0x40
                c = (c & 0x38) | ink
            elif op == 0xDF:
                d, e = mem[addr], mem[addr + 1]
                addr += 2
            elif op == 0xE0:
                c = mem[addr]
                addr += 1
            elif op == 0xE1:
                stack.append([mem[addr], addr + 1])
                addr += 1
            elif op == 0xE2:
                top = stack[-1]
                top[0] -= 1
                if top[0]:
                    addr = top[1]
                else:
                    stack.pop()
            elif op == 0xE3:
                sub = mem[addr] | (mem[addr + 1] << 8)
                addr += 2
                if depth < 8:
                    self.run(sub, screen, d, e, c, base, solid, hit, depth + 1)
            elif op == 0xE4:
                n, t = mem[addr], mem[addr + 1]
                addr += 2
                for _ in range(n):
                    self._tile(screen, d, e, t, base, c, solid, hit)
                    e = (e + 1) & 0xFF
            elif op == 0xE5:
                n, t = mem[addr], mem[addr + 1]
                addr += 2
                for _ in range(n):
                    self._tile(screen, d, e, t, base, c, solid, hit)
                    d = (d + 1) & 0xFF
            elif op == 0xE6:
                base = mem[addr] | (mem[addr + 1] << 8)
                addr += 2
            elif op == 0xE7:
                self._tile(screen, d, e, 0x20, SPECIAL_BASE, c, solid, hit)
                e = (e + 1) & 0xFF
            elif op == 0xE8:
                solid = mem[addr]
                addr += 1
            elif op == 0xE9:
                hit = 0
            elif op == 0xEA:
                hit = 0xFF
            elif op == 0xEB:
                addr += 1       # animation hook: no effect on a still frame
            else:
                return d, e, c, base, solid, hit

    def _tile(self, screen, d, e, code, base, attr, solid, hit):
        if e & 0x20:            # BIT 5,E -> RET NZ in the original
            return
        src = (base + code * 8) & 0xFFFF
        screen.plot(d, e, self.mem[src:src + 8], attr, solid, hit)


# --------------------------------------------------------------- zone data --
def zone_table(mem):
    return [mem[ZONE_PTRS + 2 * i] | (mem[ZONE_PTRS + 2 * i + 1] << 8)
            for i in range(ZONE_COUNT)]


def zone_objects(mem, zone):
    """[(row, col, obj), ...] for one zone."""
    ptr = zone_table(mem)[zone]
    out = []
    while mem[ptr] != 0xFF:
        out.append((mem[ptr], mem[ptr + 1], mem[ptr + 2]))
        ptr += 3
    return out


def object_table(mem):
    return [mem[OBJ_PTRS + 2 * i] | (mem[OBJ_PTRS + 2 * i + 1] << 8)
            for i in range(OBJ_COUNT)]


def object_boxes(mem):
    """object -> (dx, w, dy, h) collision box, from the table at 0x94C6."""
    out = {}
    p = OBJ_BOXES
    while not (mem[p] & 0x80):
        out[mem[p]] = tuple(mem[p + 1:p + 5])
        p += 5
    return out


def render_zone(mem, zone):
    """Paint one zone exactly the way the original's loader does."""
    scr = Screen()
    runner = ListRunner(mem)
    objs = object_table(mem)
    for row, col, obj in zone_objects(mem, zone):
        runner.run(objs[obj], scr, row=row, col=col, attr=0x07,
                   base=0, solid=1, hit=0)
    return scr


# ------------------------------------------------------------- rendering --
ZXPAL = [(0, 0, 0), (0, 0, 205), (205, 0, 0), (205, 0, 205),
         (0, 205, 0), (0, 205, 205), (205, 205, 0), (205, 205, 205)]
ZXPAL_B = [(0, 0, 0), (0, 0, 255), (255, 0, 0), (255, 0, 255),
           (0, 255, 0), (0, 255, 255), (255, 255, 0), (255, 255, 255)]


def screen_to_image(scr, zoom=2):
    from PIL import Image
    img = Image.new("RGB", (SCR_COLS * 8, SCR_ROWS * 8))
    px = img.load()
    for r in range(SCR_ROWS):
        for c in range(SCR_COLS):
            a = scr.attr[r][c]
            pal = ZXPAL_B if a & 0x40 else ZXPAL
            ink, paper = pal[a & 7], pal[(a >> 3) & 7]
            g = scr.pix[r][c]
            for y in range(8):
                b = g[y]
                for x in range(8):
                    px[c * 8 + x, r * 8 + y] = ink if b & (0x80 >> x) else paper
    if zoom != 1:
        img = img.resize((img.width * zoom, img.height * zoom), Image.NEAREST)
    return img
