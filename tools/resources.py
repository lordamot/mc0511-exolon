#!/usr/bin/env python3
"""Readers for the editable resources under src/res/.

Shared by the MACRO-11 generators (tools/*_gen.py) and by
tools/verify_build.py, which re-renders the zones from these files and
compares them with the original game.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "src/res"

# display-list opcodes, as emitted into the game image
OP_MOVE0 = 0x78          # 'move dr dc'   : op = 0x78 + dr, then dc
OP_NL0 = 0xAF            # 'nl dc'        : op = 0xAF + dc  (row += 1)
OP_INK0 = 0xCF           # 'ink n'        : op = 0xCF + n
OP_AT = 0xDF
OP_ATTR = 0xE0
OP_REP = 0xE1
OP_ENDREP = 0xE2
OP_CALL = 0xE3
OP_HRUN = 0xE4
OP_VRUN = 0xE5
OP_BASE = 0xE6
OP_SOLID = 0xE8
OP_HIT = 0xE9            # 'hit 0'; 'hit 255' is 0xEA
OP_HITF = 0xEA
OP_END = 0xFF


def _lines(path):
    for raw in Path(path).read_text().splitlines():
        line = raw.split(";")[0].strip()
        if line:
            yield line


# ------------------------------------------------------------------ tiles --
def read_tiles(path=RES / "tiles/tiles.txt"):
    """-> [bytes(8), ...] indexed by tile number (ZX bit order: bit 7 =
    leftmost pixel)."""
    tiles, cur, rows = {}, None, []

    def flush():
        if cur is not None:
            if len(rows) != 8:
                raise ValueError(f"tile {cur}: {len(rows)} rows, want 8")
            tiles[cur] = bytes(
                sum(0x80 >> i for i, c in enumerate(r) if c == "#")
                for r in rows)

    for line in _lines(path):
        if line.startswith("tile "):
            flush()
            cur, rows = int(line.split()[1]), []
        else:
            rows.append(line)
    flush()
    n = max(tiles) + 1
    return [tiles.get(i, bytes(8)) for i in range(n)]


# ---------------------------------------------------------- display lists --
def read_aliases(path=RES / "objects/objects.txt"):
    """-> {NAME: list id} for the lists the engine refers to by name."""
    out = {}
    for line in _lines(path):
        if line.startswith("alias "):
            _, name, num = line.split()
            out[name] = int(num)
    return out


def read_lists(path=RES / "objects/objects.txt"):
    """-> [[(op, args...), ...], ...] indexed by list id."""
    lists, cur = {}, None
    for line in _lines(path):
        if line.startswith("alias "):
            continue
        if line.startswith("list "):
            cur = int(line.split()[1])
            lists[cur] = []
            continue
        parts = line.split()
        lists[cur].append(tuple([parts[0]] + [int(x) for x in parts[1:]]))
    return [lists[i] for i in range(max(lists) + 1)]


def assemble_list(ops, list_addr):
    """One display list -> bytes.  `list_addr` maps a list id to the
    address of its assembled bytes (for 'call')."""
    out = bytearray()
    for op in ops:
        k = op[0]
        if k == "tile":
            out.append(op[1])
        elif k == "move":
            out += bytes([(OP_MOVE0 + op[1]) & 0xFF, op[2] & 0xFF])
        elif k == "nl":
            out.append((OP_NL0 + op[1]) & 0xFF)
        elif k == "ink":
            out.append(OP_INK0 + op[1])
        elif k == "at":
            out += bytes([OP_AT, op[1] & 0xFF, op[2] & 0xFF])
        elif k == "attr":
            out += bytes([OP_ATTR, op[1] & 0xFF])
        elif k == "rep":
            out += bytes([OP_REP, op[1] & 0xFF])
        elif k == "endrep":
            out.append(OP_ENDREP)
        elif k == "call":
            a = list_addr[op[1]]
            out += bytes([OP_CALL, a & 0xFF, (a >> 8) & 0xFF])
        elif k == "hrun":
            out += bytes([OP_HRUN, op[1] & 0xFF, op[2] & 0xFF])
        elif k == "vrun":
            out += bytes([OP_VRUN, op[1] & 0xFF, op[2] & 0xFF])
        elif k == "base":
            out += bytes([OP_BASE, op[1] & 0xFF, (op[1] >> 8) & 0xFF])
        elif k == "solid":
            out += bytes([OP_SOLID, op[1] & 0xFF])
        elif k == "hit":
            out.append(OP_HITF if op[1] else OP_HIT)
        elif k == "end":
            out.append(OP_END)
        else:
            raise ValueError(f"unknown display-list op {k!r}")
    return bytes(out)


def layout_lists(lists, org):
    """Assemble every list at consecutive addresses starting at `org`.
    Two passes, because 'call' needs the addresses."""
    addr, sizes = {}, {}
    pos = org
    for i, ops in enumerate(lists):
        addr[i] = pos
        sizes[i] = len(assemble_list(ops, {j: 0 for j in range(len(lists))}))
        pos += sizes[i]
    blob = bytearray()
    for i, ops in enumerate(lists):
        blob += assemble_list(ops, addr)
    return addr, bytes(blob)


# ------------------------------------------------------------------ zones --
def read_zones(path=RES / "zones/zones.txt"):
    """-> [[(row, col, obj), ...], ...] indexed by zone number."""
    zones, cur = {}, None
    for line in _lines(path):
        if line.startswith("zone "):
            cur = int(line.split()[1])
            zones[cur] = []
        else:
            r, c, o = (int(x) for x in line.split())
            zones[cur].append((r, c, o))
    return [zones[i] for i in range(max(zones) + 1)]


def read_boxes(path=RES / "objects/boxes.txt"):
    """-> {object: (dx, w, dy, h)} with signed dx/dy."""
    out = {}
    for line in _lines(path):
        p = line.split()
        if p[0] != "box":
            continue
        out[int(p[1])] = tuple(int(x) for x in p[2:6])
    return out


# ---------------------------------------------------------------- sprites --
def read_frames(path, width_bytes):
    """Sprite sheet -> [bytes, ...], row-major, `width_bytes` per row."""
    frames, cur, rows = {}, None, []

    def flush():
        if cur is not None:
            data = bytearray()
            for r in rows:
                for b in range(width_bytes):
                    chunk = r[b * 8:b * 8 + 8]
                    data.append(sum(0x80 >> i for i, c in enumerate(chunk)
                                    if c == "#"))
            frames[cur] = bytes(data)

    for line in _lines(path):
        if line.startswith("frame "):
            flush()
            cur, rows = int(line.split()[1]), []
        else:
            rows.append(line)
    flush()
    return [frames[i] for i in range(max(frames) + 1)]
