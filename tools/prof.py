#!/usr/bin/env python3
"""Rough in-game CPU profile from the headless emulator.

    prof.py ZONE [--samples N] [--warmup F]

Boots build/exolon.dsk, starts a game, jumps to the given zone with
the cheat pokes, then single-steps the emulator N times reading the
CPU program counter, and prints the busiest code labels - the symbol
table comes from build/exolon.lst.  A sample is one emulated frame,
so the counts say where whole frames go, not instruction counts.

Run `make build` first; the listing and the disk must be in build/.
"""

import argparse
import re
import subprocess
import sys
from bisect import bisect_right
from collections import Counter
from pathlib import Path

# an unhandled exception should land in the terminal, not in Ubuntu's
# apport crash-report dialog (apport installs a system-wide excepthook)
sys.excepthook = sys.__excepthook__


ROOT = Path(__file__).resolve().parent.parent
LST = ROOT / "build/exolon.lst"
DSK = ROOT / "build/exolon.dsk"
EMU = ROOT / "bin/ukncbtl/uknc-headless"
ROM = ROOT / "bin/ukncbtl/uknc_rom.bin"

# a label line: line number, octal address, optional machine words,
# then "NAME:" as the first source token (so text in comments never
# passes for a label)
SYM_RE = re.compile(
    r"^\s*\d+\s+([0-7]{6})\s+(?:[0-7]{3,6}'?\s+){0,4}([A-Z][A-Z_0-9.$]*):")


def read_symbols():
    if not LST.exists():
        sys.exit(f"error: {LST} not found - run `make build` first")
    sym = {}
    for line in LST.read_text().splitlines():
        m = SYM_RE.match(line)
        if m:
            sym.setdefault(m.group(2), int(m.group(1), 8))
    for need in ("ZONE", "ZONELOAD", "CHEAT"):
        if need not in sym:
            sys.exit(f"error: symbol {need} not in {LST} - stale listing?")
    return sym


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("zone", type=int, help="zone to profile, 0..124")
    ap.add_argument("--samples", type=int, default=200,
                    help="frames to sample (default 200)")
    ap.add_argument("--warmup", type=int, default=60,
                    help="frames to run after the zone poke (default 60)")
    a = ap.parse_args(argv)
    if not 0 <= a.zone <= 124:
        sys.exit("error: zone must be 0..124")
    for f, what in ((DSK, "disk (run `make build`)"), (EMU, "emulator"),
                    (ROM, "ROM")):
        if not f.exists():
            sys.exit(f"error: {f} not found - missing {what}")

    sym = read_symbols()
    labels = sorted((addr, name) for name, addr in sym.items()
                    if addr >= 0o2000)

    s = ("run 900\npress 030\nrun 30\npress 153\nrun 500\n"
         "press 30 3\nrun 40\n"
         f"pokecpu {sym['CHEAT']:o} 1 0\n"
         f"pokecpu {sym['ZONE']:o} {a.zone:o} 0\n"
         f"pokecpu {sym['ZONELOAD']:o} 1 0\n"
         f"run {a.warmup}\n")
    s += "run 1\nregs\n" * a.samples + "quit\n"

    r = subprocess.run([str(EMU), "--rom", str(ROM), "--disk", str(DSK),
                        "--script", "/dev/stdin"],
                       input=s, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"error: emulator exited {r.returncode}:\n{r.stderr[-500:]}")

    cnt = Counter()
    for line in r.stdout.splitlines():
        m = re.search(r"CPU PC=([0-7]{6})", line)
        if m:
            pc = int(m.group(1), 8)
            i = bisect_right(labels, (pc, "￿")) - 1
            cnt[labels[i][1] if i >= 0 else hex(pc)] += 1
    if not cnt:
        sys.exit("error: no PC samples in the emulator output")
    for name, c in cnt.most_common(12):
        print(f"{c:4} {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
