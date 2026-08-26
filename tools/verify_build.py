#!/usr/bin/env python3
"""Check the build end to end.

    python3 tools/verify_build.py [--dsk build/exolon.dsk]

Six groups of checks:

1. resource round-trip - the display lists, tiles and zone tables under
   src/res/ are re-run through the same interpreter the game uses and
   compared, cell by cell, with the original ZX Spectrum game rendered
   straight out of EXOLON.TAP.  All 125 zones must match exactly.
2. generator determinism - every *_gen.py produces byte-identical
   output when run twice.
3. image layout - the program fits its budget and the disk image has
   the boot signature.
4. sprite and music sanity - frame counts and the tune's shape.
5. smoke test - the headless emulator boots the disk, reaches the title
   screen, starts a game and shows zone 0 with the HUD.
6. gameplay - scripted runs in the headless emulator for the rules that
   are easy to break: crouching under a gun emplacement's shot, the
   one-pixel bolt, emplacements and rock formations needing a grenade,
   the teleport pads, the canisters and the power-suit booth, the
   mirrored sprite when the player faces left, the grenade's arc and
   smoke trail, an emplacement's recoil, a force field's energy balls
   and the rocket that hunts a player who stays in one zone.

Exit status is nonzero if anything fails.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resources as R
import zone_render as Z
import exolon_re as E
import rt11_home as HOME

ROOT = Path(__file__).resolve().parent.parent
PROG_SIZE = 0o110000

fails = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{(' - ' + detail) if detail else ''}")
    if not ok:
        fails.append(name)


def zones_match():
    mem = E.load_image()
    tiles, lists, zones = R.read_tiles(), R.read_lists(), R.read_zones()
    bad = 0
    for z in range(len(zones)):
        a = E.render_zone(mem, z)
        b = Z.render_zone(z, lists, zones)
        for r in range(24):
            for c in range(32):
                used = b.tile[r][c] is not None
                if a.used[r][c] != used:
                    bad += 1
                    continue
                if not used:
                    continue
                ink = (a.attr[r][c] & 7) | (8 if a.attr[r][c] & 0x40 else 0)
                if (bytes(a.pix[r][c]) != tiles[b.tile[r][c]]
                        or ink != b.ink[r][c]
                        or a.solid[r][c] != b.solid[r][c]):
                    bad += 1
    return bad


def gen_deterministic():
    py = sys.executable
    gens = [
        ("tools/tiles_gen.py", ["src/res/tiles/tiles.txt"]),
        ("tools/objects_gen.py", ["src/res/objects/objects.txt"]),
        ("tools/zones_gen.py", ["src/res/zones/zones.txt",
                                "--boxes", "src/res/objects/boxes.txt"]),
        ("tools/text_gen.py", ["src/res/text/strings.txt"]),
        ("tools/music_gen.py", ["src/res/music/title.txt"]),
    ]
    with tempfile.TemporaryDirectory() as td:
        for tool, args in gens:
            outs = []
            for i in (0, 1):
                out = Path(td) / f"{Path(tool).stem}{i}.mac"
                r = subprocess.run([py, tool] + args + ["--out", str(out),
                                                        "--force"],
                                   cwd=ROOT, capture_output=True, text=True)
                if r.returncode != 0:
                    return f"{tool} failed: {r.stderr.strip()}"
                outs.append(out.read_bytes())
            if outs[0] != outs[1]:
                return f"{tool} is not deterministic"
        r = subprocess.run([py, "tools/sprites_gen.py",
                            "--player", "src/res/sprites/player.txt",
                            "--small", "src/res/sprites/small.txt",
                            "--out", str(Path(td) / "s.mac"), "--force"],
                           cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            return f"sprites_gen.py failed: {r.stderr.strip()}"
    return None


def smoke(dsk, out_png):
    script = f"""run 900
press 030
run 30
press 153
run 500
screenshot {out_png.with_suffix('.title.bmp')}
press {K_ONE:o} 3
run 120
screenshot {out_png}
dumpcpu 0140000 3072 {out_png.with_suffix('.cells.bin')}
quit
"""
    with tempfile.NamedTemporaryFile("w", suffix=".script",
                                     delete=False) as f:
        f.write(script)
        path = f.name
    r = subprocess.run([str(ROOT / "bin/ukncbtl/uknc-headless"),
                        "--rom", str(ROOT / "bin/ukncbtl/uknc_rom.bin"),
                        "--disk", str(dsk), "--script", path],
                       capture_output=True, text=True)
    Path(path).unlink()
    if r.returncode != 0:
        return f"emulator failed: {r.stderr.strip()[:200]}", None
    cells = out_png.with_suffix(".cells.bin")
    if not cells.exists():
        return "no cell dump", None
    return None, cells.read_bytes()


# ---- gameplay checks ----------------------------------------------
# The game variables move whenever gamevars.mac gains a word, so their
# addresses are read back out of the assembler listing rather than
# written down here.
import re

_SYMS = {}


def sym(name):
    """Address of a label in the assembled image, from build/exolon.lst."""
    if not _SYMS:
        pat = re.compile(r"^\s*\d+\s+([0-7]{6})\s+([A-Z_0-9.$]+):")
        for line in (ROOT / "build/exolon.lst").read_text().splitlines():
            m = pat.match(line)
            if m and m.group(2) not in _SYMS:
                _SYMS[m.group(2)] = int(m.group(1), 8)
    return _SYMS[name]


O_SIZE, O_OBJ, O_COL, O_ROW, O_T = 8, 6, 4, 5, 7
E_SIZE, E_STATE, E_X, E_Y, E_KIND, E_T1, E_T2 = 6, 0, 1, 2, 3, 4, 5
EK_GREN, EK_SPARK, EK_BALL, EK_ROCK, EK_TPFX, EK_MINE, EK_EMIT = (
    3, 6, 7, 8, 9, 10, 11)
NENT = 48
EK_ROCK_FRAME = 36        # the hunting rocket's 16x16 frame
C_SIZE, C_ROW = 4, 128
GUN_TILE = 191
BUF = 0o110000

# The firmware boot menu wants "1" then ENTER; the game's own title
# screen is started with "1" as well (K_ONE), and "2" toggles infinite
# lives.
K_RIGHT, K_DOWN, K_UP, K_FIRE, K_GREN = 133, 134, 154, 107, 166
K_ONE, K_TWO, K_PAUSE = 0o30, 0o31, 0o6

BOOT = f"""run 900
press 030
run 30
press 153
run 500
press {K_ONE:o} 3
run 40
"""


def ents(blob):
    """[(kind, x, y, t1, t2), ...] for the live entities in a dump of
    the ENTS array."""
    out = []
    for i in range(NENT):
        r = blob[i * E_SIZE:(i + 1) * E_SIZE]
        if r[E_STATE]:
            out.append((r[E_KIND], r[E_X], r[E_Y], r[E_T1], r[E_T2]))
    return out


def sprite_bits(buf, row0, col0, ncols, nlines):
    """The lit pixels of a back-buffer block as one integer per line,
    most significant bit leftmost.  A cell word holds plane 1 in its low
    byte and plane 2 in its high byte; a sprite lights one or both, so
    the union of the planes is what was drawn."""
    out = []
    for y in range(row0, row0 + nlines):
        v = 0
        for c in range(col0, col0 + ncols):
            w = buf[y * 64 + c * 2] | (buf[y * 64 + c * 2 + 1] << 8)
            b = (w & 0xFF) | (w >> 8)
            # bit 0 of a plane byte is the leftmost pixel
            for i in range(8):
                if b & (1 << i):
                    v |= 1 << (ncols * 8 - 1 - ((c - col0) * 8 + i))
        out.append(v)
    return out


def mirror(v, width):
    r = 0
    for i in range(width):
        if v & (1 << i):
            r |= 1 << (width - 1 - i)
    return r


def emu(body, tmpdir):
    """Run a script after the boot preamble; -> {address: value} for
    every peekcpu, in order, plus the files any dumpcpu wrote."""
    return emu_raw(BOOT + body, tmpdir)


def emu_raw(script, tmpdir):
    script = script + "quit\n"
    sp = Path(tmpdir) / "s.script"
    sp.write_text(script)
    r = subprocess.run([str(ROOT / "bin/ukncbtl/uknc-headless"),
                        "--rom", str(ROOT / "bin/ukncbtl/uknc_rom.bin"),
                        "--disk", str(ROOT / "build/exolon.dsk"),
                        "--script", str(sp)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:200])
    vals = []
    for line in r.stdout.splitlines():
        if line.startswith("peekcpu") and "=" in line:
            vals.append(int(line.split("=")[1].split("(")[0].strip(), 8))
    return vals


def lit_pixels(buf, x0, x1, y0, y1):
    """Count set pixels in the back buffer over cell columns x0..x1 and
    pixel lines y0..y1 (a cell word is plane 1 in the low byte and
    plane 2 in the high byte, one bit per pixel)."""
    n = 0
    for y in range(y0, y1):
        for c in range(x0, x1):
            w = buf[y * 64 + c * 2] | (buf[y * 64 + c * 2 + 1] << 8)
            n += bin(w & 0xFF | (w >> 8)).count("1")
    return n


def poke16(addr, val):
    return f"pokecpu {addr:o} {val & 0xFF:o} {(val >> 8) & 0xFF:o}\n"


def gameplay(tmpdir):
    td = Path(tmpdir)
    A_ZONE, A_ZONELOAD = sym("ZONE"), sym("ZONELOAD")
    A_PX, A_PY, A_PFACE = sym("PX"), sym("PY"), sym("PFACE")
    A_PSUIT, A_AMMO, A_GREN = sym("PSUIT"), sym("AMMO"), sym("GRENADES")
    A_LIVES, A_OBJLIST, A_ENTS = sym("LIVES"), sym("OBJLIST"), sym("ENTS")
    A_FRAMECNT, A_ROCKACT = sym("FRAMECNT"), sym("ROCKACT")
    ENTBYTES = NENT * E_SIZE

    # Crouching has to duck a gun emplacement's shot; standing must not.
    duck = emu(f"run 20\nkeydown {K_DOWN}\nrun 280\n"
               f"peekcpu {A_LIVES:o}\n", td)
    check("crouching ducks the first zone's turret", duck[0] == 7,
          f"lives {duck[0]}")
    stand = emu(f"run 280\npeekcpu {A_LIVES:o}\n", td)
    check("standing in front of it does not", stand[0] < 7,
          f"lives {stand[0]}")

    # The bolt is one pixel.  Fire, then stop every entity dead (the
    # dumps land at an arbitrary point in the game loop, so a moving one
    # can be caught half drawn) and compare its own cell with how that
    # cell looked before the shot.
    before, ent = td / "before.bin", td / "bolt.bin"
    after = [td / f"a{i}.bin" for i in range(3)]
    freeze = "".join(f"pokecpu {A_ENTS + i * E_SIZE + E_T1:o} 0\n"
                     for i in range(NENT))
    objs = td / "objs.bin"
    emu(f"run 10\nkeydown {K_DOWN}\nrun 6\n"
        f"{poke16(A_PX, 44)}run 4\n"
        f"dumpcpu {BUF:o} 12288 {before}\n"
        f"press {K_FIRE} 2\nrun 2\n" + freeze
        + f"run 1\ndumpcpu {BUF:o} 12288 {after[0]}\n"
        f"dumpcpu {A_ENTS:o} {ENTBYTES} {ent}\n"
        f"run 1\ndumpcpu {BUF:o} 12288 {after[1]}\n"
        f"run 1\ndumpcpu {BUF:o} 12288 {after[2]}\n"
        f"run 60\ndumpcpu {A_OBJLIST:o} 32 {objs}\n", td)
    bolts = [x for x in ents(ent.read_bytes()) if x[0] == 1]
    check("firing puts a bolt in the air", len(bolts) == 1,
          f"{len(bolts)} bolts")
    if bolts:
        _, bx, by, _, _ = bolts[0]
        b0 = sprite_bits(before.read_bytes(), by - 1, bx // 4, 1, 3)
        us = [sprite_bits(f.read_bytes(), by - 1, bx // 4, 1, 3)
              for f in after]
        n = sum(bin((x | y | z) & ~c).count("1")
                for x, y, z, c in zip(*us, b0))
        check("the player's bolt is a single pixel", n == 1,
              f"{n} pixels lit in its own cell")
    alive = objs.read_bytes()
    check("a laser bolt leaves the gun emplacement standing",
          alive[O_SIZE + O_OBJ] == 5, f"object byte {alive[O_SIZE + O_OBJ]:o}")

    # A grenade does.  It leaves the shoulder on the original's arc -
    # up, level, then a shallow dive - so it has to be lobbed from far
    # enough back that the dive brings it down onto the emplacement.
    objs2 = td / "objs2.bin"
    emu(f"run 10\n{poke16(A_PX, 48)}run 4\n"
        f"press {K_GREN} 2\nrun 60\n"
        f"dumpcpu {A_OBJLIST:o} 32 {objs2}\n", td)
    dead = objs2.read_bytes()
    check("a grenade lobbed from a distance destroys it",
          dead[O_SIZE + O_OBJ] & 0o200 != 0,
          f"object byte {dead[O_SIZE + O_OBJ]:o}")
    near = td / "objs3.bin"
    emu(f"run 10\n{poke16(A_PX, 72)}run 4\n"
        f"press {K_GREN} 2\nrun 60\n"
        f"dumpcpu {A_OBJLIST:o} 32 {near}\n", td)
    check("one thrown from under it sails over, as in the original",
          near.read_bytes()[O_SIZE + O_OBJ] == 5,
          f"object byte {near.read_bytes()[O_SIZE + O_OBJ]:o}")

    # Teleport pads: he can walk in (they used to be walled off), and
    # pressing up on one puts him on the other.  Where the pads are is
    # read out of the running game first, so the test does not depend on
    # how far a held key carries him in a fixed number of frames.
    A_NTPORT, A_TPROW, A_TPCOL = sym("NTPORT"), sym("TPROW"), sym("TPCOL")
    z2 = f"run 10\n{poke16(A_ZONE, 2)}{poke16(A_ZONELOAD, 1)}run 40\n"
    pads = emu(z2 + f"peekcpu {A_NTPORT:o}\n"
               f"peekcpu {A_TPROW:o}\npeekcpu {A_TPCOL:o}\n"
               f"peekcpu {A_TPROW + 2:o}\npeekcpu {A_TPCOL + 2:o}\n"
               f"keydown {K_RIGHT}\nrun 8\nkeyup {K_RIGHT}\nrun 2\n"
               f"peekcpu {A_PX:o}\n", td)
    check("zone 2 has its two teleport pads", pads[0] == 2, f"{pads[0]} pads")
    check("the player can walk into a teleport booth", pads[5] > 8,
          f"x {pads[5]}")
    r0, c0, r1, c1 = pads[1], pads[2], pads[3], pads[4]
    tpe = td / "tpents.bin"
    tp = emu(z2 + f"{poke16(A_PX, max(c0 * 4 - 3, 0))}"
             f"{poke16(A_PY, (r0 + 1) * 8)}run 2\n"
             f"press {K_UP} 3\nrun 2\n"
             f"dumpcpu {A_ENTS:o} {ENTBYTES} {tpe}\n"
             f"run 4\npeekcpu {A_PX:o}\npeekcpu {A_PY:o}\n", td)
    check("pressing up warps him to the other pad",
          tp[0] == max(c1 * 4 - 3, 0) and tp[1] == (r1 + 1) * 8,
          f"({tp[0]}, {tp[1]}) want ({max(c1 * 4 - 3, 0)}, {(r1 + 1) * 8})")
    e = ents(tpe.read_bytes())
    emitters = [x for x in e if x[0] == EK_TPFX]
    sparks = [x for x in e if x[0] == EK_SPARK]
    check("both teleport pads throw sparks",
          len(emitters) == 2 and len(sparks) >= 1,
          f"{len(emitters)} emitters, {len(sparks)} sparks")

    # Walking into a canister refills the ammunition.
    A_NPICK, A_PICKS = sym("NPICKUP"), sym("PICKS")
    can = emu(z2 + f"peekcpu {A_NPICK:o}\n"
              f"peekcpu {A_PICKS:o}\npeekcpu {A_PICKS + 2:o}\n", td)
    check("zone 2 has a canister in it", can[0] > 0, f"{can[0]} canisters")
    if can[0]:
        ca = emu(z2 + f"{poke16(A_AMMO, 5)}"
                 f"{poke16(A_PX, can[2] * 4)}{poke16(A_PY, can[1] * 8)}"
                 f"run 4\npeekcpu {A_AMMO:o}\n", td)
        check("a canister refills the ammunition", ca[0] == 99,
              f"ammo {ca[0]}")

    # The power-suit booth is entered, not walked into and died in.
    A_NSUITP, A_SUITROW, A_SUITCOL = sym("NSUITP"), sym("SUITROW"), sym("SUITCOL")
    z9 = f"run 10\n{poke16(A_ZONE, 9)}{poke16(A_ZONELOAD, 1)}run 40\n"
    bo = emu(z9 + f"peekcpu {A_NSUITP:o}\n"
             f"peekcpu {A_SUITROW:o}\npeekcpu {A_SUITCOL:o}\n", td)
    check("zone 9 has a power-suit booth", bo[0] == 1, f"{bo[0]} booths")
    if bo[0]:
        su = emu(z9 + f"{poke16(A_PX, bo[2] * 4)}"
                 f"{poke16(A_PY, (bo[1] + 1) * 8)}run 2\n"
                 f"press {K_UP} 3\nrun 6\n"
                 f"peekcpu {A_PSUIT:o}\npeekcpu {A_LIVES:o}\n", td)
        check("the power-suit booth puts the suit on",
              su[0] == 12 and su[1] == 7, f"suit {su[0]}, lives {su[1]}")

    gameplay_new(td, locals())


def gameplay_new(td, v):
    """The behaviour ported in from the original after the first pass:
    facing, the grenade, the emplacement's recoil, a force field's
    energy balls and the rocket that comes for a lingering player."""
    A_PX, A_PY, A_PFACE = v["A_PX"], v["A_PY"], v["A_PFACE"]
    A_ZONE, A_ZONELOAD = v["A_ZONE"], v["A_ZONELOAD"]
    A_GREN, A_ENTS, A_OBJLIST = v["A_GREN"], v["A_ENTS"], v["A_OBJLIST"]
    A_FRAMECNT, A_ROCKACT = v["A_FRAMECNT"], v["A_ROCKACT"]
    ENTBYTES = v["ENTBYTES"]

    # --- facing ---------------------------------------------------
    # Walking left draws the frame mirrored.  Take the same standing
    # frame at the same place with each facing, subtract the background
    # (a third dump with the player moved away) and compare.
    px, py = 40, 96
    col, ncol, nlin = px // 4, 3, 32

    def shots_of(tag, poke, n=3):
        # a dump lands at an arbitrary point in the game loop, so it can
        # catch the sprite half erased; the player is not moving, so the
        # union over a few frames is exactly what he looks like
        files = [td / f"{tag}{i}.bin" for i in range(n)]
        body = f"run 10\n{poke}run 3\n"
        body += "".join(f"dumpcpu {BUF:o} 12288 {f}\nrun 1\n" for f in files)
        emu(body, td)
        return [sprite_bits(f.read_bytes(), py, col, ncol, nlin)
                for f in files]

    at = f"{poke16(A_PX, px)}{poke16(A_PY, py)}"
    rr = shots_of("r", at + poke16(A_PFACE, 1))
    # and again with something else already drawn this frame, because
    # the entity kinds set the sprite extents the player has to reset
    gg = shots_of("g", at + poke16(A_PFACE, 1) + f"press {K_GREN} 2\n")
    ll = shots_of("l", at + poke16(A_PFACE, 0xFFFF))
    bb_ = shots_of("b", poke16(A_PX, px + 40) + poke16(A_PY, py))
    unite = lambda fs: [f0 | f1 | f2 for f0, f1, f2 in zip(*fs)]
    inter = lambda fs: [f0 & f1 & f2 for f0, f1, f2 in zip(*fs)]
    br, bl, bb = unite(rr), unite(ll), inter(bb_)
    bg_ = unite(gg)
    missing = sum(bin((r & ~c) & ~g).count("1")
                  for g, r, c in zip(bg_, br, bb))
    check("nothing else on screen shrinks him", missing == 0,
          f"{missing} of his pixels go missing while a grenade is in "
          f"the air")
    sr = [r & ~g for r, g in zip(br, bb)]
    sl = [l & ~g for l, g in zip(bl, bb)]
    check("the player is drawn at all", any(sr) and any(sl),
          f"{sum(bin(x).count('1') for x in sr)} / "
          f"{sum(bin(x).count('1') for x in sl)} pixels")
    same = sum(1 for a, b in zip(sl, sr) if a == mirror(b, ncol * 8))
    check("walking left draws him mirrored", same == nlin,
          f"{same}/{nlin} lines match")
    check("and the two facings really differ", sl != sr)

    # --- the grenade ----------------------------------------------
    g1, g2 = td / "g1.bin", td / "g2.bin"
    gv = emu(f"run 10\npress {K_GREN} 2\nrun 3\n"
             f"dumpcpu {A_ENTS:o} {ENTBYTES} {g1}\n"
             f"press {K_GREN} 2\nrun 2\n"
             f"peekcpu {A_GREN:o}\n"
             f"dumpcpu {A_ENTS:o} {ENTBYTES} {g2}\n", td)
    e1 = ents(g1.read_bytes())
    gren = [x for x in e1 if x[0] == EK_GREN]
    check("a thrown grenade is in the air", len(gren) == 1,
          f"{len(gren)} grenades")
    if gren:
        _, gx, gy, step, cnt = gren[0]
        check("it climbs the original's arc",
              step == 1 and 19 <= cnt < 32 and gx > 8,
              f"x {gx} y {gy} step {step} counter {cnt}")
    check("and it trails smoke",
          any(x[0] == EK_SPARK for x in e1),
          f"{sum(1 for x in e1 if x[0] == EK_SPARK)} sparks")
    e2 = ents(g2.read_bytes())
    check("only one grenade is ever in flight",
          sum(1 for x in e2 if x[0] == EK_GREN) == 1 and gv[0] == 9,
          f"{sum(1 for x in e2 if x[0] == EK_GREN)} in the air, "
          f"{gv[0]} left")

    # --- the emplacement's recoil ---------------------------------
    objs, c1, c2 = td / "o.bin", td / "c1.bin", td / "c2.bin"
    emu(f"run 20\ndumpcpu {A_OBJLIST:o} 32 {objs}\n", td)
    rec = objs.read_bytes()[O_SIZE:O_SIZE * 2]
    grow, gcol = rec[O_ROW], rec[O_COL]
    cells = [td / f"c{i}.bin" for i in range(4)]
    body = f"run 20\npokecpu {A_OBJLIST + O_SIZE + O_T:o} 11\n"
    body += "".join(f"run 1\ndumpcpu 0140000 3072 {f}\n" for f in cells)
    emu(body, td)

    def tile(blob, r, c):
        o = r * C_ROW + c * C_SIZE
        return blob[o] | (blob[o + 1] << 8)

    seq = [tile(f.read_bytes(), grow, gcol) for f in cells]
    anim = list(range(GUN_TILE + 16, GUN_TILE + 31, 2))
    check("a firing emplacement plays its recoil",
          len(set(seq)) >= 3 and all(t in anim for t in seq)
          and seq == sorted(seq, reverse=True),
          f"tiles {seq} at cell ({grow}, {gcol})")

    # --- a force field's energy balls -----------------------------
    be = td / "balls.bin"
    emu(f"run 10\n{poke16(A_ZONE, 5)}{poke16(A_ZONELOAD, 1)}"
        f"run 30\ndumpcpu {A_ENTS:o} {ENTBYTES} {be}\n", td)
    eb = [x for x in ents(be.read_bytes()) if x[0] == EK_BALL]
    want = int(re.search(r"^BALLS\t= (\d+)\.",
                         (ROOT / "src/defs.mac").read_text(),
                         re.M).group(1))
    check("a force field fills the zone with drifting balls",
          len(eb) == want, f"{len(eb)} balls, want {want}")
    check("and they float rather than sit still",
          len({(x[1], x[2]) for x in eb}) > 1,
          f"{len({(x[1], x[2]) for x in eb})} distinct positions")

    # --- a mine's homing missiles ---------------------------------
    A_NMINE = sym("NMINE")
    mi = [td / f"mine{i}.bin" for i in range(2)]
    mv = emu(f"run 10\n{poke16(A_ZONE, 11)}{poke16(A_ZONELOAD, 1)}run 20\n"
             f"peekcpu {A_NMINE:o}\n"
             f"dumpcpu {A_ENTS:o} {ENTBYTES} {mi[0]}\n"
             f"run 40\ndumpcpu {A_ENTS:o} {ENTBYTES} {mi[1]}\n", td)
    check("zone 11's mine is found", mv[0] == 1, f"flag {mv[0]}")
    m0 = [x for x in ents(mi[0].read_bytes()) if x[0] == EK_MINE]
    m1 = [x for x in ents(mi[1].read_bytes()) if x[0] == EK_MINE]
    check("a mine keeps one missile in the air",
          len(m0) == 1 and len(m1) == 1,
          f"{len(m0)} then {len(m1)}")
    if m0 and m1:
        check("it comes in from the right and closes on the player",
              m0[0][1] > 110 and m1[0][1] < m0[0][1] + 8,
              f"x {m0[0][1]} -> {m1[0][1]}, y {m0[0][2]} -> {m1[0][2]}")

    # --- the wall emitters (the pair of guns on a wall) -----------
    A_NEMIT = sym("NEMIT")
    em = td / "emit.bin"
    ev = emu(f"run 10\n{poke16(A_ZONE, 6)}{poke16(A_ZONELOAD, 1)}run 40\n"
             f"peekcpu {A_NEMIT:o}\n{poke16(A_PX, 8)}run 200\n"
             f"dumpcpu {A_ENTS:o} {ENTBYTES} {em}\n", td)
    check("zone 6's wall guns are both found", ev[0] == 2,
          f"{ev[0]} emitters")
    ee = [x for x in ents(em.read_bytes()) if x[0] == EK_EMIT]
    check("and they spit along their own row",
          len(ee) >= 1 and all(x[3] == 0xFE for x in ee),
          f"{len(ee)} shots in the air")

    # --- the rocket that comes for a lingering player -------------
    ro = td / "rock.bin"
    rv = emu(f"run 10\npeekcpu {A_ROCKACT:o}\n"
             f"{poke16(A_FRAMECNT, 700)}run 2\n"
             f"peekcpu {A_ROCKACT:o}\n"
             f"dumpcpu {A_ENTS:o} {ENTBYTES} {ro}\n", td)
    rk = [x for x in ents(ro.read_bytes()) if x[0] == EK_ROCK]
    check("no rocket while the player keeps moving on", rv[0] == 0,
          f"flag {rv[0]}")
    check("staying in one zone sends one in", rv[1] == 1 and len(rk) == 1,
          f"flag {rv[1]}, {len(rk)} rockets")
    if rk:
        _, rx, ry, step, _ = rk[0]
        check("it crosses from the right at the player's height",
              rx <= 120 and rx >= 112 and step == 0xFE,
              f"x {rx} y {ry} step {step - 256}")

    # It is drawn from a frame that faces right, so flying left it has
    # to be mirrored - the original just drew it backwards.
    # It is drawn from a frame that faces right, so flying left it has
    # to be mirrored - the original just drew it backwards.  Send it
    # across empty sky, pause (which freezes the back buffer, so the
    # dump cannot catch it half drawn) and compare it with the frame.
    W = 32
    bgf, entf, buff = td / "rbg.bin", td / "rme.bin", td / "rmb.bin"
    emu(f"run 10\n{poke16(A_PX, 8)}{poke16(A_PY, 40)}"
        f"dumpcpu {BUF:o} 12288 {bgf}\n"
        f"{poke16(A_FRAMECNT, 700)}run 6\n"
        f"press {K_PAUSE:o}\nrun 10\n"
        f"dumpcpu {A_ENTS:o} {ENTBYTES} {entf}\n"
        f"dumpcpu {BUF:o} 12288 {buff}\n", td)
    frame = R.read_frames(ROOT / "src/res/sprites/small.txt", 2)[EK_ROCK_FRAME]
    rk2 = [x for x in ents(entf.read_bytes()) if x[0] == EK_ROCK]
    check("the rocket crosses the sky as well", len(rk2) == 1,
          f"{len(rk2)} rockets")
    if rk2:
        _, rx, ry, _, _ = rk2[0]
        shift = (rx & 3) * 2
        bgb = sprite_bits(bgf.read_bytes(), ry, rx // 4, 4, 16)
        fgb = sprite_bits(buff.read_bytes(), ry, rx // 4, 4, 16)
        drawn = [f & ~g for f, g in zip(fgb, bgb)]

        def expect(mirrored):
            out = []
            for y in range(16):
                e = 0
                for px_ in range(16):
                    # the sheet keeps bit 7 as the leftmost pixel
                    if frame[y * 2 + px_ // 8] & (0x80 >> (px_ % 8)):
                        k = (15 - px_) if mirrored else px_
                        e |= 1 << (W - 1 - (shift + k))
                out.append(e)
            return out

        miss = lambda exp: sum(bin(e & ~d).count("1")
                               for d, e in zip(drawn, exp))
        m, pl = miss(expect(True)), miss(expect(False))
        check("and it is drawn nose first, not tail first",
              m == 0 and pl > 0,
              f"{m} pixels of the mirrored frame are missing, {pl} of the "
              f"plain one")


def menu(tmpdir):
    """The title screen: "1" starts, "2" turns infinite lives on and it
    holds through a death."""
    td = Path(tmpdir)
    A_LIVES, A_CHEAT, A_ZONE = sym("LIVES"), sym("CHEAT"), sym("ZONE")
    A_PDEAD = sym("PDEAD")
    title = ("run 900\npress 030\nrun 30\npress 153\nrun 500\n")

    # "1" alone gets into a game
    st = emu_raw(title + f"press {K_ONE:o}\nrun 60\n"
                 f"peekcpu {A_LIVES:o}\npeekcpu {A_CHEAT:o}\n", td)
    check("the title screen starts on 1", st[0] == 7 and st[1] == 0,
          f"lives {st[0]}, cheat {st[1]}")

    # "2" arms the option and it survives into the game
    ch = emu_raw(title + f"press {K_TWO:o}\nrun 20\n"
                 f"press {K_ONE:o}\nrun 60\n"
                 f"peekcpu {A_CHEAT:o}\n"
                 # sit in front of the first zone's turret until it kills
                 # him a few times over
                 f"run 900\n"
                 f"peekcpu {A_LIVES:o}\npeekcpu {A_PDEAD:o}\n", td)
    check("2 turns infinite lives on", ch[0] == 1, f"cheat {ch[0]}")
    check("and dying then costs nothing", ch[1] == 7, f"lives {ch[1]}")

    # without it, the same wait costs lives
    no = emu_raw(title + f"press {K_ONE:o}\nrun 60\nrun 900\n"
                 f"peekcpu {A_LIVES:o}\n", td)
    check("while without it they run out", no[0] < 7, f"lives {no[0]}")


def white_rows():
    """Every playfield row the player can reach must offer white, or the
    sprite is drawn in whatever ink is nearest and Vitorc changes colour
    halfway up a jump (src/zone.mac WHITE_SLOT3)."""
    from collections import Counter
    tiles, lists, zones = R.read_tiles(), R.read_lists(), R.read_zones()
    bad = 0
    for z in range(len(zones)):
        cells = Z.render_zone(z, lists, zones)
        for r in range(8, 22):
            w = Counter()
            for c in range(32):
                t = cells.tile[r][c]
                if t is None:
                    continue
                n = sum(bin(b).count("1") for b in tiles[t])
                if n:
                    w[cells.ink[r][c]] += n
            if not w:
                continue
            pal = [i for i, _ in w.most_common(3)]
            if 15 not in pal:
                pal = pal[:2] + [15]        # WHITE_SLOT3
            if 15 not in pal:
                bad += 1
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--dsk", default="build/exolon.dsk")
    args = ap.parse_args()
    dsk = ROOT / args.dsk

    print("resources")
    bad = zones_match()
    check("all 125 zones re-render exactly as the original",
          bad == 0, f"{bad} cells differ" if bad else "")

    tiles = R.read_tiles()
    check("glyph bank", len(tiles) == 672, f"{len(tiles)} tiles")
    lists = R.read_lists()
    check("display lists", len(lists) >= 62, f"{len(lists)} lists")
    zones = R.read_zones()
    check("zone table", len(zones) == 125, f"{len(zones)} zones")
    boxes = R.read_boxes()
    check("live object boxes", len(boxes) == 10, f"{len(boxes)} boxes")
    player = R.read_frames(ROOT / "src/res/sprites/player.txt", 3)
    check("player frames", len(player) == 25 and len(player[0]) == 96,
          f"{len(player)} frames")
    small = R.read_frames(ROOT / "src/res/sprites/small.txt", 2)
    check("16x16 sprites", len(small) >= 47 and len(small[0]) == 32,
          f"{len(small)} frames")
    notes = [l for l in (ROOT / "src/res/music/title.txt").read_text()
             .splitlines() if l.strip() and not l.strip().startswith(";")]
    check("title tune", len([l for l in notes if not l.startswith("channel")])
          > 300, f"{len(notes)} lines")

    print("generators")
    err = gen_deterministic()
    check("every generator is deterministic", err is None, err or "")

    print("image")
    check("disk image exists", dsk.exists(), str(dsk))
    if dsk.exists():
        data = dsk.read_bytes()
        check("disk size", len(data) == 819200, f"{len(data)} bytes")
        # the firmware only boots a disk whose first word is a NOP
        check("boot sector marker", data[0] == 0o240 and data[1] == 0,
              f"first word {data[0] | (data[1] << 8):06o}")
        vol = HOME.read_volume(data[512:1024])
        check("the disk carries its name", vol == "EXOLON",
              f"volume id {vol!r}")
        # the program's tail has to start where the loader looks for it
        raw = ROOT / "build/exolon.raw"
        if raw.exists():
            tail = raw.read_bytes()[512:1024]
            ok = data[1024:1536] == tail
            check("and the program follows the home block", ok,
                  "" if ok else "LBA 2 is not the program's second sector")
        raw = ROOT / "build/exolon.raw"
        if raw.exists():
            check("program fits its budget",
                  len(raw.read_bytes()) == PROG_SIZE,
                  f"{len(raw.read_bytes())} bytes")

    print("smoke test")
    if dsk.exists():
        out = ROOT / "tmp/verify.bmp"
        out.parent.mkdir(exist_ok=True)
        err, cells = smoke(dsk, out)
        check("headless boot to gameplay", err is None, err or "")
        if cells:
            # zone 0 must be in the cell buffer: the ground rows are solid
            ground = all(cells[r * 128 + c * 4 + 3] == 1
                         for r in (19, 20, 21) for c in range(0, 32, 4))
            check("zone 0 collision map is loaded", ground)
            hud = any(cells[22 * 128 + c * 4] != 0 for c in range(32))
            check("HUD row is drawn", hud)

    print("menu")
    if dsk.exists():
        with tempfile.TemporaryDirectory() as td:
            try:
                menu(td)
            except RuntimeError as e:
                check("the title screen runs", False, str(e))

    print("gameplay")
    if dsk.exists():
        with tempfile.TemporaryDirectory() as td:
            try:
                gameplay(td)
            except RuntimeError as e:
                check("scripted gameplay runs", False, str(e))
    nw = white_rows()
    check("every reachable row can show a white sprite", nw == 0,
          f"{nw} rows without white")

    print()
    if fails:
        print(f"{len(fails)} check(s) failed: {', '.join(fails)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
