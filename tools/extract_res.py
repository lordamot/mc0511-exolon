#!/usr/bin/env python3
"""Extract the editable game resources from EXOLON.TAP into src/res/.

Run once (the files are the source of truth afterwards):

    python3 tools/extract_res.py [--force]

Written resources:

    src/res/tiles/tiles.txt        672 8x8 glyphs (font + scenery tiles)
    src/res/objects/objects.txt    the scenery display lists
    src/res/zones/zones.txt        125 zones as {row, col, object} triples
    src/res/sprites/player.txt     25 player frames, 24x32
    src/res/sprites/small.txt      57 sprites, 16x16
    src/res/text/strings.txt       menu / HUD strings

See .claude/docs/re-notes.md for where each of these lives in the
original and what the display-list byte code means.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from exolon_re import (ROOT, load_image, zone_objects, object_table,
                       object_boxes, ZONE_COUNT, OBJ_COUNT, SPECIAL_BASE)

RES = ROOT / "src/res"

# One flat tile bank: everything the game draws as an 8x8 glyph.
TILE_ORG = 0xD7E0
TILE_END = 0xECE0
TILE_COUNT = (TILE_END - TILE_ORG) // 8      # 672

PLAYER_ORG, PLAYER_FRAMES, PLAYER_W, PLAYER_H = 0xEF80, 25, 3, 32
SMALL_ORG, SMALL_FRAMES, SMALL_W, SMALL_H = 0xF8E0, 57, 2, 16


def bits(byte):
    return "".join("#" if byte & (0x80 >> i) else "." for i in range(8))


def tile_index(addr):
    if not (TILE_ORG <= addr < TILE_END) or (addr - TILE_ORG) % 8:
        raise ValueError(f"tile address {addr:#06x} outside the bank")
    return (addr - TILE_ORG) // 8


# ----------------------------------------------------------- display lists --
# Opcode names used in objects.txt.  The generator (tools/objects_gen.py)
# turns them straight back into the same byte code, with the tile base
# expressed as an index into the tile bank instead of an address.
def parse_list(mem, addr):
    """Linear parse of one display list -> [(op, args...)], plus the
    addresses it calls."""
    ops, calls = [], []
    base = None
    while True:
        op = mem[addr]
        addr += 1
        if op < 0x61:
            ops.append(("tile", op))
        elif op < 0x90:
            ops.append(("move", op - 0x78, mem[addr]))
            addr += 1
        elif op < 0xCF:
            ops.append(("nl", op - 0xAF))
        elif op < 0xDF:
            ops.append(("ink", op - 0xCF))
        elif op == 0xDF:
            ops.append(("at", mem[addr], mem[addr + 1]))
            addr += 2
        elif op == 0xE0:
            ops.append(("attr", mem[addr]))
            addr += 1
        elif op == 0xE1:
            ops.append(("rep", mem[addr]))
            addr += 1
        elif op == 0xE2:
            ops.append(("endrep",))
        elif op == 0xE3:
            tgt = mem[addr] | (mem[addr + 1] << 8)
            addr += 2
            ops.append(("call", tgt))
            calls.append(tgt)
        elif op == 0xE4:
            ops.append(("hrun", mem[addr], mem[addr + 1]))
            addr += 2
        elif op == 0xE5:
            ops.append(("vrun", mem[addr], mem[addr + 1]))
            addr += 2
        elif op == 0xE6:
            base = mem[addr] | (mem[addr + 1] << 8)
            ops.append(("base", base))
            addr += 2
        elif op == 0xE7:
            # the original swaps the tile base in and straight back out
            if base is None:
                raise ValueError(f"list {addr:#06x}: E7 with no base set")
            ops += [("base", SPECIAL_BASE), ("tile", 0x20), ("base", base)]
        elif op == 0xE8:
            ops.append(("solid", mem[addr]))
            addr += 1
        elif op == 0xE9:
            ops.append(("hit", 0))
        elif op == 0xEA:
            ops.append(("hit", 0xFF))
        elif op == 0xEB:
            ops.append(("anim", mem[addr]))  # runtime animation hook
            addr += 1
        else:
            ops.append(("end",))
            return ops, calls, addr


# display lists that are not scenery objects but worth keeping: the
# original's menu screen draws its EXOLON logo with one of these.
EXTRA_LISTS = {"LOGO": 0x70FF}


def collect_lists(mem):
    """All display lists reachable from the 62 object entries.  Ids 0..61
    are the object entries themselves - two objects that share an address
    still get an id each, so the zone data indexes them directly - and the
    sub-lists that the E3 opcode calls follow."""
    entries = object_table(mem)
    ids = {}                       # address -> id used by 'call'
    order = list(entries)          # id -> address (duplicates kept)
    for i, a in enumerate(entries):
        ids.setdefault(a, i)
    parsed, pending = {}, list(entries) + list(EXTRA_LISTS.values())
    while pending:
        a = pending.pop(0)
        if a in parsed:
            continue
        ops, calls, _ = parse_list(mem, a)
        parsed[a] = ops
        if a not in ids:
            ids[a] = len(order)
            order.append(a)
        pending.extend(c for c in calls if c not in parsed)
    return order, ids, parsed


def write_objects(mem, path):
    order, ids, parsed = collect_lists(mem)
    aliases = {n: ids[a] for n, a in EXTRA_LISTS.items()}
    out = ["; Exolon scenery display lists (see .claude/docs/re-notes.md).",
           "; 'list N' - N is the list id; the first 62 are the object ids",
           "; the zone data refers to.  Cursor is (row, col) in cells;",
           "; 'base' is a tile-bank index, 'ink' a ZX ink 0..15 (8..15 are",
           "; the bright half), 'solid' the class written into the collision",
           "; map for every cell drawn afterwards.",
           "; 'alias NAME id' names a list the code refers to by symbol.",
           ""]
    for n, i in sorted(aliases.items()):
        out.append(f"alias {n} {i}")
    out.append("")
    for i, a in enumerate(order):
        who = f"   ; object {i}" if i < OBJ_COUNT else "   ; sub-list"
        out.append(f"list {i}{who}")
        for op in parsed[a]:
            k = op[0]
            if k == "tile":
                out.append(f"  tile {op[1]}")
            elif k == "move":
                out.append(f"  move {op[1]} {op[2]}")
            elif k == "nl":
                out.append(f"  nl {op[1]}")
            elif k == "ink":
                out.append(f"  ink {op[1]}")
            elif k == "at":
                out.append(f"  at {op[1]} {op[2]}")
            elif k == "attr":
                out.append(f"  attr {op[1]}")
            elif k == "rep":
                out.append(f"  rep {op[1]}")
            elif k == "endrep":
                out.append("  endrep")
            elif k == "call":
                out.append(f"  call {ids[op[1]]}")
            elif k == "hrun":
                out.append(f"  hrun {op[1]} {op[2]}")
            elif k == "vrun":
                out.append(f"  vrun {op[1]} {op[2]}")
            elif k == "base":
                out.append(f"  base {tile_index(op[1])}")
            elif k == "solid":
                out.append(f"  solid {op[1]}")
            elif k == "hit":
                out.append(f"  hit {op[1]}")
            elif k == "end":
                out.append("  end")
        out.append("")
    path.write_text("\n".join(out))
    return len(order)


def write_zones(mem, path):
    boxes = object_boxes(mem)
    out = ["; Exolon zones: one 'zone N' block per screen, then one line",
           "; per placed object: <cell row> <cell col> <object>.",
           "; A column >= 128 is negative (the object hangs off the left).",
           "; Objects with a bounding box below are the live ones: the",
           "; player and bullets collide with them.", ";",
           "; object  dx   w  dy   h"]
    for k, (dx, w, dy, h) in sorted(boxes.items()):
        out.append(f";   {k:3d} {dx - 256 if dx > 127 else dx:4d} {w:3d} "
                   f"{dy - 256 if dy > 127 else dy:3d} {h:3d}")
    out.append("")
    for z in range(ZONE_COUNT):
        out.append(f"zone {z}")
        for row, col, obj in zone_objects(mem, z):
            out.append(f"  {row} {col} {obj}")
        out.append("")
    path.write_text("\n".join(out))


def write_boxes(mem, path):
    boxes = object_boxes(mem)
    out = ["; Bounding boxes of the live scenery objects, from the table at",
           "; 0x94C6 in the original: <object> <dx> <w> <dy> <h>, in the",
           "; game's units (x in 2-pixel steps, y in pixels), relative to",
           "; the object's cell position.", ""]
    for k, (dx, w, dy, h) in sorted(boxes.items()):
        out.append(f"box {k} {dx - 256 if dx > 127 else dx} {w} "
                   f"{dy - 256 if dy > 127 else dy} {h}")
    path.write_text("\n".join(out) + "\n")


def write_tiles(mem, path):
    out = ["; Exolon 8x8 glyph bank: the text font (indices 0..95, ASCII",
           "; from space) followed by the scenery tiles.  '#' = ink pixel.",
           "; Display lists address these by index (see objects.txt).", ""]
    for i in range(TILE_COUNT):
        a = TILE_ORG + i * 8
        out.append(f"tile {i}")
        out += [bits(mem[a + y]) for y in range(8)]
        out.append("")
    path.write_text("\n".join(out))


# The original draws the grenade, the sparks and the force field's energy
# balls from a second, 16x8 pre-shifted bank at 0xED40 that has nothing to
# do with the 16x16 sheet (plotter 0x92FB), and it has no sprite at all for
# the player's own laser bolt.  The port has one sprite format for all of
# them, so those frames are copied into the sheet's unused slots, in the
# sheet's own bit order, and the port's entity code names them there.
SMALL_BANK = 0xED40             # 16x8 frames, 4 pre-shifts of 16 bytes each
SMALL_BANK_FRAMES = {           # sheet frame -> bank frame
    46: 0,                      # grenade flying right
    47: 1,                      # grenade flying left
    48: 7,                      # a force field's energy ball
    49: 3,                      # spark, three sizes (0x9864 picks between
    50: 4,                      # them as the spark's counter runs out)
    51: 5,
    52: 8,                      # a wall emitter's shot
}

# The power suit's own bolt: the original has no sprite for the player's
# fire at all (it drew a bare pattern), and the port needs a visibly
# heavier one for the two-gun shot the suit gives him.  It sits in the
# frame's top rows so the entity's y is the top of the bar.
EXTRA_SMALL = {
    45: [".###########....", ".###########...."] + ["." * 16] * 14,
}


def bank_frame(mem, n):
    """One 16x8 frame of the second sprite bank, padded to 16x16."""
    a = SMALL_BANK + n * 64     # shift 0 of the four pre-shifted copies
    return [bits(mem[a + y * 2]) + bits(mem[a + y * 2 + 1])
            for y in range(8)] + ["." * 16] * 8


def write_sprites(mem, path, org, count, w, h, title, extra=None):
    out = [f"; {title}: {count} frames of {w * 8}x{h} pixels.", ""]
    for i in range(count):
        out.append(f"frame {i}")
        if extra and i in extra:
            out += extra[i]
        else:
            for y in range(h):
                out.append("".join(bits(mem[org + i * w * h + y * w + b])
                                   for b in range(w)))
        out.append("")
    path.write_text("\n".join(out))



STRINGS = """\
; Game strings: label|text (plain ASCII).  Characters are drawn as
; tiles: the glyph bank holds the font at tile index = ASCII code.
TITLE|EXOLON
AUTHOR|BY RAFFAELE CECCO
PORT|UKNC PORT
START|1 START GAME
LIVESOPT|2 INFINITE LIVES
ON|ON
OFF|OFF
COPY|HEWSON 1987
AMMO|AMMO
GREN|GRENADES
POINTS|POINTS
LIVES|LIVES
ZONES|ZONES
GAMEOVER|GAME OVER
PAUSED|PAUSED
"""


def small_extra(mem):
    out = dict(EXTRA_SMALL)
    for frame, n in SMALL_BANK_FRAMES.items():
        out[frame] = bank_frame(mem, n)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    mem = load_image()
    for sub in ("tiles", "objects", "zones", "sprites", "text",
                "music", "pics"):
        (RES / sub).mkdir(parents=True, exist_ok=True)

    targets = {
        RES / "tiles/tiles.txt": lambda p: write_tiles(mem, p),
        RES / "objects/objects.txt": lambda p: write_objects(mem, p),
        RES / "objects/boxes.txt": lambda p: write_boxes(mem, p),
        RES / "zones/zones.txt": lambda p: write_zones(mem, p),
        RES / "sprites/player.txt": lambda p: write_sprites(
            mem, p, PLAYER_ORG, PLAYER_FRAMES, PLAYER_W, PLAYER_H,
            "Player frames (0..9 walk, 10 crouch, 11 death, 12..23 the "
            "same in the power suit, 24 ground cannon)"),
        RES / "sprites/small.txt": lambda p: write_sprites(
            mem, p, SMALL_ORG, SMALL_FRAMES, SMALL_W, SMALL_H,
            "16x16 sprites (0..9 explosion, 10..15 rockets and missiles, "
            "16..19 energy balls, 36 the rocket that hunts a player who\n; lingers, 45 the power suit's bolt, 46/47 a grenade, 48 an energy ball,\n; 49..51 sparks, 52 a wall emitter's shot)",
            small_extra(mem)),
        RES / "text/strings.txt": lambda p: p.write_text(STRINGS),
    }
    for path, fn in targets.items():
        if path.exists() and not args.force:
            print(f"  keep  {path.relative_to(ROOT)} (exists)")
            continue
        fn(path)
        print(f"  write {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
