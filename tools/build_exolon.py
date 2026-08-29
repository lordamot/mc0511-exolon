#!/usr/bin/env python3
"""Build the game: src/ -> build/exolon.dsk (bootable raw image).

Steps: run the resource generators (tiles, display lists, zones,
sprites, strings, music), concatenate the MACRO-11 modules listed in
src/exolon.list, assemble with bin/macro11 (-yus -ysl 64), link flat
with tools/obj2bin.py, and lay out the raw disk (program at LBA 0).

Usage: build_exolon.py [OUT.dsk] [--force]
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
PROG_SIZE = 0o117000        # must match PROG_SIZE in src/defs.mac
BUF = 0o107000              # and BUF: the back buffer overlays the PPU
                            # block, so the live program must end below it
DISK_SIZE = 819200
SECTOR = 512
VOLUME = "EXOLON"           # the disk's name, in the RT-11 home block


def run(*cmd):
    r = subprocess.run([str(c) for c in cmd], cwd=ROOT,
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        sys.exit(f"error: {' '.join(str(c) for c in cmd)} failed")
    return r


def main():
    out = ROOT / (sys.argv[1] if len(sys.argv) > 1
                  and not sys.argv[1].startswith("-") else "build/exolon.dsk")
    BUILD.mkdir(exist_ok=True)
    py = sys.executable

    run(py, "tools/tiles_gen.py", "src/res/tiles/tiles.txt",
        "--out", "build/data_tiles.mac", "--force")
    run(py, "tools/objects_gen.py", "src/res/objects/objects.txt",
        "--out", "build/data_lists.mac", "--force")
    run(py, "tools/zones_gen.py", "src/res/zones/zones.txt",
        "--boxes", "src/res/objects/boxes.txt",
        "--out", "build/data_zones.mac", "--force")
    run(py, "tools/sprites_gen.py",
        "--player", "src/res/sprites/player.txt",
        "--small", "src/res/sprites/small.txt",
        "--out", "build/data_sprites.mac", "--force")
    run(py, "tools/text_gen.py", "src/res/text/strings.txt",
        "--out", "build/strings.mac", "--force")
    run(py, "tools/music_gen.py", "src/res/music/title.txt",
        "--out", "build/data_music.mac", "--force")

    modules = []
    for line in (ROOT / "src/exolon.list").read_text().splitlines():
        line = line.split(";")[0].strip()
        if line:
            modules.append(ROOT / line)
    src = "\n".join(m.read_text() for m in modules)
    (BUILD / "exolon.mac").write_text(src)

    r = run(ROOT / "bin/macro11/macro11", "-yus", "-ysl", "64",
            "-o", "build/exolon.obj", "-l", "build/exolon.lst",
            "build/exolon.mac")
    if "***ERROR" in r.stdout or "***ERROR" in r.stderr:
        sys.exit("error: assembler reported errors (see build/exolon.lst)")

    # The PPU block is the image's tail and the back buffer overlays it;
    # everything the game still needs after the load has to end below BUF.
    m = re.search(r"^\s*\d+\s+([0-7]+)\s.*\bPP_START:", 
                  (BUILD / "exolon.lst").read_text(), re.M)
    if not m:
        sys.exit("error: cannot find PP_START in build/exolon.lst")
    if int(m.group(1), 8) > BUF:
        sys.exit(f"error: the live program ends at 0{m.group(1)}, past the "
                 f"back buffer at 0{BUF:o}")
    run(py, "tools/obj2bin.py", "build/exolon.obj", "build/exolon.raw",
        "--size", str(PROG_SIZE))

    # LBA 0 is the boot sector, LBA 1 the RT-11 home block that names the
    # disk, and the rest of the program follows from LBA 2 (the loader's
    # parameter block in src/boot.mac says the same).
    raw = (BUILD / "exolon.raw").read_bytes()
    (BUILD / "boot.raw").write_bytes(raw[:SECTOR])
    (BUILD / "main.raw").write_bytes(raw[SECTOR:])
    run(py, "tools/rt11_home.py", "build/home.raw",
        "--volume", VOLUME, "--force")

    manifest = {"geometry": {"size": DISK_SIZE},
                "entries": [{"file": "boot.raw", "lba": 0, "sectors": 1},
                            {"file": "home.raw", "lba": 1, "sectors": 1},
                            {"file": "main.raw", "lba": 2,
                             "sectors": PROG_SIZE // SECTOR - 1}]}
    (BUILD / "manifest.json").write_text(json.dumps(manifest, indent=1))
    run(py, "tools/dsk_build.py", "build/manifest.json", out, "--force")
    print(f"{out}: OK ({PROG_SIZE} byte program, volume {VOLUME})")


if __name__ == "__main__":
    main()
