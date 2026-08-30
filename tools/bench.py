#!/usr/bin/env python3
"""Game frame rate of a built disk, measured in the headless emulator.

    bench.py [--dsk build/exolon.dsk] [--lst build/exolon.lst]
             [--baseline OTHER.dsk [--baseline-lst OTHER.lst]]
             [--zones 0,2,10,...] [--ticks 100] [--busy]

The game loop is not locked to the 50 Hz tick: it draws as fast as it
can and BENCHF counts the frames it finished (gamevars.mac).  So the
frames it gets through in a fixed slice of *hardware* time is the plain
measure of how much work a frame costs, and the one an optimisation
pass moves.

Each zone is loaded, the player put back on his feet, and the frame
counter read before and after `ticks` hardware frames (1/25 s each).
By default the runtime animations, the flyers, the emitters and the
mines are switched off first, which is what makes two runs comparable:
they spawn off a random source, and once two builds disagree about
what is on screen they are no longer measuring the same scene.  --busy
leaves them running - closer to real play, noisier to compare.

With --baseline the same sweep is run against a second disk and the
two are printed side by side.  Give --baseline-lst when the other disk
was built from different sources (the symbol addresses move).
"""

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.excepthook = sys.__excepthook__

ROOT = Path(__file__).resolve().parent.parent
EMU = ROOT / "bin/ukncbtl/uknc-headless"
ROM = ROOT / "bin/ukncbtl/uknc_rom.bin"

# hardware frames a second, and CPU ticks in one of them: the KM1801VM2
# runs 16 times per 2 us system tick, 20000 of those to a 1/25 s frame
HW_FPS = 25
CPU_TICKS_PER_HW_FRAME = 320000

K_ONE = 0o30
BOOT = f"""run 900
press 030
run 30
press 153
run 500
press {K_ONE:o} 3
run 40
"""

# a spread over the zone table: open ground, the busy scenery zones,
# the ones with pylons, pumps, a laser beam and the level gates
DEFAULT_ZONES = (0, 2, 3, 6, 7, 10, 11, 20, 24, 25, 35, 60, 90, 124)


def symbols(lst):
    pat = re.compile(r"^\s*\d+\s+([0-7]{6})\s+([A-Z_0-9.$]+):")
    out = {}
    for line in Path(lst).read_text().splitlines():
        m = pat.match(line)
        if m and m.group(2) not in out:
            out[m.group(2)] = int(m.group(1), 8)
    if "BENCHF" not in out:
        sys.exit(f"error: no BENCHF in {lst} - stale listing?")
    return out


def poke16(addr, val):
    return f"pokecpu {addr:o} {val & 0xFF:o} {(val >> 8) & 0xFF:o}\n"


def run_script(dsk, script):
    with tempfile.NamedTemporaryFile("w", suffix=".script") as f:
        f.write(script + "quit\n")
        f.flush()
        r = subprocess.run([str(EMU), "--rom", str(ROM), "--disk", str(dsk),
                            "--script", f.name], capture_output=True,
                           text=True)
    if r.returncode != 0:
        sys.exit(f"error: emulator failed: {r.stderr.strip()[:300]}")
    return [int(l.split("=")[1].split("(")[0].strip(), 8)
            for l in r.stdout.splitlines()
            if l.startswith("peekcpu") and "=" in l]


def still(sym):
    """Switch off everything that spawns off the random source."""
    return "".join(poke16(sym[n], 0) for n in
                   ("FLYON", "NFLM", "NCYC", "NMIN5", "NPUMPS", "BEAMON",
                    "NEMIT"))


def sweep(dsk, lst, zones, ticks, busy):
    sym = symbols(lst)
    out = {}
    for z in zones:
        script = (BOOT + "run 10\n"
                  + poke16(sym["ZONE"], z) + poke16(sym["ZONELOAD"], 1)
                  + "run 60\n"
                  + poke16(sym["PDEAD"], 0) + poke16(sym["LIVES"], 7)
                  + ("" if busy else still(sym))
                  + "run 10\n"
                  + f"peekcpu {sym['BENCHF']:o}\n"
                  + f"run {ticks}\n"
                  + f"peekcpu {sym['BENCHF']:o}\n")
        a, b = run_script(dsk, script)
        out[z] = (b - a) & 0xFFFF
    return out


def report(frames, ticks):
    secs = ticks / HW_FPS
    for z, n in frames.items():
        print(f"  zone {z:3d}   {n / secs:5.1f} fps"
              f"   {CPU_TICKS_PER_HW_FRAME * ticks / max(n, 1):9.0f} "
              f"CPU ticks/frame")
    tot = sum(frames.values())
    print(f"  {'total':>9}   {tot / (secs * len(frames)):5.1f} fps"
          f"   {CPU_TICKS_PER_HW_FRAME * ticks * len(frames) / max(tot, 1):9.0f} "
          f"CPU ticks/frame")
    return tot


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--dsk", default="build/exolon.dsk")
    ap.add_argument("--lst", default="build/exolon.lst")
    ap.add_argument("--baseline", help="second disk to compare against")
    ap.add_argument("--baseline-lst",
                    help="its listing (default: the same --lst)")
    ap.add_argument("--zones", default=",".join(str(z) for z in DEFAULT_ZONES))
    ap.add_argument("--ticks", type=int, default=100,
                    help="hardware frames per zone (default 100 = 4 s)")
    ap.add_argument("--busy", action="store_true",
                    help="leave the animations and the flyers running")
    args = ap.parse_args(argv)

    zones = [int(z) for z in args.zones.split(",") if z.strip()]
    for p in (EMU, ROM, Path(args.dsk), Path(args.lst)):
        if not Path(p).exists():
            sys.exit(f"error: {p} not found - run `make build` first")

    print(f"{args.dsk} ({'busy' if args.busy else 'still'} scenes, "
          f"{args.ticks} hardware frames a zone)")
    new = report(sweep(args.dsk, args.lst, zones, args.ticks, args.busy),
                 args.ticks)
    if args.baseline:
        print(f"\n{args.baseline}")
        old = report(sweep(args.baseline, args.baseline_lst or args.lst,
                           zones, args.ticks, args.busy), args.ticks)
        print(f"\n  {args.dsk} runs {(new / old - 1) * 100:+.1f}% of the "
              f"frames the baseline does")
    return 0


if __name__ == "__main__":
    sys.exit(main())
