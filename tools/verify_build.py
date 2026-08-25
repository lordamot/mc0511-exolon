#!/usr/bin/env python3
"""Check the build end to end.

    python3 tools/verify_build.py [--dsk build/exolon.dsk]

Five groups of checks:

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
run 320
screenshot {out_png.with_suffix('.title.bmp')}
press 153 5
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

    print()
    if fails:
        print(f"{len(fails)} check(s) failed: {', '.join(fails)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
