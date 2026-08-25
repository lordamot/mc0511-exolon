#!/usr/bin/env python3
"""Parse a ZX Spectrum .TAP file: list its blocks and extract them.

A .TAP is a sequence of [len:2][flag:1][data:len-2][checksum in data].
Header blocks (flag 0) are 17 data bytes: type, 10-char name, length,
param1, param2.  Data blocks (flag 255) carry the payload.

Usage:
  python3 tools/tap_extract.py list  FILE.TAP
  python3 tools/tap_extract.py save  FILE.TAP OUTDIR   (each block -> file)
"""
import sys
import struct
from pathlib import Path

TYPES = {0: "Program", 1: "NumArray", 2: "CharArray", 3: "Bytes"}


def blocks(data: bytes):
    off = 0
    while off + 2 <= len(data):
        (blen,) = struct.unpack_from("<H", data, off)
        off += 2
        blk = data[off : off + blen]
        off += blen
        yield blk


def parse(path: Path):
    data = path.read_bytes()
    out = []
    header = None
    for blk in blocks(data):
        flag = blk[0]
        body = blk[1:-1]  # strip flag and checksum
        chk = 0
        for b in blk[:-1]:
            chk ^= b
        ok = chk == blk[-1]
        if flag == 0 and len(body) == 17:
            btype = body[0]
            name = body[1:11].decode("latin1").rstrip()
            length, p1, p2 = struct.unpack_from("<HHH", body, 11)
            header = (btype, name, length, p1, p2)
            out.append(("header", header, ok, body))
        else:
            out.append(("data", header, ok, body))
            header = None
    return out


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    cmd, path = sys.argv[1], Path(sys.argv[2])
    items = parse(path)
    if cmd == "list":
        for i, (kind, hdr, ok, body) in enumerate(items):
            if kind == "header":
                btype, name, length, p1, p2 = hdr
                extra = ""
                if btype == 3:
                    extra = f" start={p1} ({p1:#06x})"
                elif btype == 0:
                    extra = f" autostart={p1}"
                print(
                    f"{i:2d} header {str(TYPES.get(btype, btype)):8s}"
                    f" name={name!r} len={length}{extra} ok={ok}"
                )
            else:
                ctx = ""
                if hdr:
                    ctx = f" for {hdr[1]!r} start={hdr[3]}"
                print(f"{i:2d} data   len={len(body)}{ctx} ok={ok}")
    elif cmd == "save":
        outdir = Path(sys.argv[3])
        outdir.mkdir(parents=True, exist_ok=True)
        prev_hdr = None
        for i, (kind, hdr, ok, body) in enumerate(items):
            if kind == "header":
                prev_hdr = hdr
                continue
            if prev_hdr:
                btype, name, length, p1, p2 = prev_hdr
                safe = "".join(c if c.isalnum() else "_" for c in name)
                fn = f"{i:02d}_{safe}_{p1}.bin" if btype == 3 else f"{i:02d}_{safe}.bin"
            else:
                fn = f"{i:02d}_headerless.bin"
            (outdir / fn).write_bytes(body)
            print(f"wrote {outdir / fn} ({len(body)} bytes)")
            prev_hdr = None
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
