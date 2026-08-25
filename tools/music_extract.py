#!/usr/bin/env python3
"""Decode Exolon's three-channel tune out of the tape image.

The 48K release only has beeper effects, but the same image carries
the 128K AY music: a player at 0xB6EC with three streams and a note ->
AY-period table at 0xC71B (see .claude/docs/re-notes.md for the stream
commands).  This walks the three streams, resolves the sub-sequence
calls and loops, and writes note events as

    channel N
      <period> <frames>      ; period 0 = rest

into src/res/music/title.txt, which tools/music_gen.py turns into the
UKNC beeper player's tables.

    python3 tools/music_extract.py [--out src/res/music/title.txt]
            [--limit 900] [--force]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from exolon_re import ROOT, load_image

STREAMS = (0xBA01, 0xBB7E, 0xBD06)
NOTETAB = 0xC71B
DEFAULT_LEN = 6


def decode(mem, start, limit):
    """-> [(period, frames), ...]"""
    out = []
    pc = start
    stack = []
    deflen = DEFAULT_LEN
    transpose = 0
    seen_jump = 0
    while len(out) < limit:
        op = mem[pc]
        pc += 1
        if op < 0x32:
            note, ln = op, deflen
        elif op < 0x64:
            note, ln = op - 0x32, mem[pc]
            deflen = ln
            pc += 1
        elif op == 0x64:
            continue
        elif op < 0x75:
            continue                       # volume floor
        elif op == 0x75:
            tgt = mem[pc] | (mem[pc + 1] << 8)
            stack.append(pc + 2)
            pc = tgt
            continue
        elif op == 0x76:
            if not stack:
                break
            pc = stack.pop()
            continue
        elif op == 0x77:
            transpose = mem[pc]
            pc += 1
            continue
        elif op == 0x78:
            tgt = mem[pc] | (mem[pc + 1] << 8)
            seen_jump += 1
            if seen_jump > 1:
                break                      # one pass through the loop
            pc = tgt
            continue
        elif op == 0x79:
            pc += 1
            continue
        elif op in (0x89, 0x8A):
            pc += mem[pc] + 1          # count byte plus count+1 values
            continue
        elif op == 0xFF:
            break
        else:
            continue
        if note == 0:
            out.append((0, ln))
            continue
        idx = (note + transpose) & 0xFF
        a = NOTETAB + idx * 2
        period = mem[a] | (mem[a + 1] << 8)
        out.append((period, ln))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--out", default=str(ROOT / "src/res/music/title.txt"))
    ap.add_argument("--limit", type=int, default=900)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if out.exists() and not a.force:
        sys.exit(f"error: {out} exists (use --force)")

    mem = load_image()
    lines = ["; Exolon title tune, decoded from the 128K AY streams in the",
             "; tape image by tools/music_extract.py.  One 'channel N'",
             "; block per voice, then '<AY period> <frames>' per note;",
             "; period 0 is a rest.  tools/music_gen.py converts the",
             "; periods into UKNC beeper half-period delays."]
    total = 0
    for ch, addr in enumerate(STREAMS):
        ev = decode(mem, addr, a.limit)
        total += len(ev)
        lines.append("")
        lines.append(f"channel {ch}")
        for p, ln in ev:
            lines.append(f"  {p} {ln}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out}: {total} note events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
