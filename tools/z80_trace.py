#!/usr/bin/env python3
"""Split a raw Z80 image into code and data by tracing control flow.

Usage:
    z80_trace.py IN.bin --org 0x9B00 [--root ADDR ...] [--skip ADDR ...]
                 [--out regions.txt]

A linear disassembler cannot tell code from data: it decodes tables and
bitmaps as nonsense instructions and then loses sync with the real code
after them. This walks the image instead -- from --root addresses, following
every call and jump, stopping at each RET/unconditional jump -- and reports
what was reached. Whatever was NOT reached is data (or code reachable only
through a computed jump, which is why the report calls those out: resolve
each JP (HL) by hand and feed its targets back in as extra --roots until the
data regions look like real data).

This is what produced .claude/docs/gamedata.md's map of the game code, and
it is the first step for any new blob: trace, resolve the computed jumps,
then hand the region map to a generator that emits code as instructions and
data as DB rows.

Output is one region per line, "code|data START END" in hex, which is easy
to consume from another script.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from z80_disasm import Decoder, Truncated

COMPUTED = ("JP (HL)", "JP (IX)", "JP (IY)")


def is_terminal(text):
    """True if control does not fall through to the next instruction."""
    if text.startswith(("JP ", "JR ")) and "," not in text:
        return True
    return text in ("RET", "RETI", "RETN")


def trace(data, org, roots, skip=()):
    """Follow control flow from `roots`. Returns (instructions, computed,
    edges) -- a dict of address -> Instr, the addresses of computed jumps,
    and a dict of traced-address -> the instruction that reached it."""
    end = org + len(data)
    dec = Decoder(data, org)
    instrs = {}
    computed = []
    edges = {}
    queue = [(r, None) for r in roots]
    seen = set()

    while queue:
        addr, source = queue.pop()
        if addr in seen or addr in skip:
            continue
        seen.add(addr)
        edges[addr] = source
        pc = addr
        while org <= pc < end and pc not in instrs:
            dec.pos = pc
            try:
                decoded = dec.decode()
            except Truncated:
                break
            for ins in decoded:
                instrs[ins.addr] = ins
                if ins.text in COMPUTED:
                    computed.append(ins.addr)
                if ins.target is not None and org <= ins.target < end:
                    queue.append((ins.target, ins.addr))
            last = decoded[-1]
            if is_terminal(last.text):
                break
            pc = last.addr + last.length
    return instrs, computed, edges


def regions_of(instrs, data, org):
    covered = bytearray(len(data))
    for addr, ins in instrs.items():
        for k in range(ins.length):
            covered[addr - org + k] = 1
    regions = []
    pos = 0
    while pos < len(data):
        kind = covered[pos]
        start = pos
        while pos < len(data) and covered[pos] == kind:
            pos += 1
        regions.append(("code" if kind else "data", org + start, org + pos))
    return regions


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input", type=Path, help="raw binary to trace")
    parser.add_argument(
        "--org", type=lambda s: int(s, 0), default=0,
        help="address of the file's first byte (accepts 0x...)",
    )
    parser.add_argument(
        "--root", type=lambda s: int(s, 0), action="append", default=[],
        help="an entry point to trace from; repeatable. Defaults to --org",
    )
    parser.add_argument(
        "--skip", type=lambda s: int(s, 0), action="append", default=[],
        help="an address never to trace into, for calls that leave this image "
        "(e.g. a vector into another memory bank); repeatable",
    )
    parser.add_argument("--out", type=Path, help="write the region map here too")
    args = parser.parse_args()

    if not args.input.is_file():
        sys.exit(f"error: {args.input} not found")
    data = args.input.read_bytes()
    roots = args.root or [args.org]
    for addr in roots + args.skip:
        if not args.org <= addr < args.org + len(data):
            sys.exit(f"error: {addr:#06x} is outside {args.input} "
                     f"({args.org:#06x}..{args.org + len(data):#06x})")

    instrs, computed, edges = trace(data, args.org, roots, set(args.skip))
    regions = regions_of(instrs, data, args.org)

    code_bytes = sum(b - a for k, a, b in regions if k == "code")
    print(f"{len(instrs)} instructions, {code_bytes} code bytes, "
          f"{len(data) - code_bytes} data bytes, {len(regions)} regions")

    if computed:
        print("\ncomputed jumps -- resolve these by hand and re-run with the "
              "targets as extra --root:")
        for addr in sorted(set(computed)):
            print(f"  {addr:04X}  {instrs[addr].text}")

    # A traced address landing inside another instruction means something was
    # decoded as code that isn't, so the map cannot be trusted as it stands.
    inside = {}
    for addr, ins in instrs.items():
        for k in range(1, ins.length):
            inside[addr + k] = addr
    conflicts = [(a, inside[a]) for a in sorted(edges) if a in inside]
    if conflicts:
        print("\nWARNING -- traced targets landing mid-instruction (the trace "
              "decoded data as code somewhere):")
        for target, host in conflicts:
            source = edges[target]
            via = f" (reached from {source:04X})" if source is not None else ""
            print(f"  {target:04X} inside the instruction at {host:04X}{via}")

    lines = [f"{kind} {a:04X} {b:04X}" for kind, a, b in regions]
    print()
    for kind, a, b in regions:
        print(f"{kind} {a:04X}..{b:04X}  ({b - a} bytes)")
    if args.out:
        args.out.write_text("\n".join(lines) + "\n")
        print(f"\nregion map -> {args.out}")


if __name__ == "__main__":
    main()
