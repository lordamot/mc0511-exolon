#!/usr/bin/env python3
"""obj2bin.py - MACRO-11 .OBJ -> flat binary image.

For fully absolute sources (.ASECT with explicit origins), collects the
TXT records of a macro11 object file into a flat memory image.

Usage:
    python3 obj2bin.py INPUT.obj OUTPUT.bin [--base ADDR] [--size N] [--debug]

  --base ADDR   octal load address of the first output byte (default 0):
                output[0] corresponds to memory address ADDR, TXT records
                below ADDR are an error.
  --size N      pad (or check) the output to exactly N bytes (decimal,
                or octal with a leading 0o / trailing .); error if the
                image is larger.
  --debug       dump record-by-record progress.
"""

import argparse
import sys

# Formatted-binary record types (per the MACRO-11 / RT-11 docs).
T_GSD = 1
T_ENDGSD = 2
T_TXT = 3
T_RLD = 4
T_ISD = 5
T_ENDMOD = 6


def iter_records(blob):
    """Yield (rec_type, payload_bytes) from a macro11 .OBJ blob.

    Framing: 01 00 LEN_LO LEN_HI TYPE_LO TYPE_HI DATA... CKSUM, where LEN
    covers header(4) + type(2) + DATA but not the checksum. Records may be
    separated by zero padding.
    """
    n = len(blob)
    i = 0
    while i < n:
        while i < n and blob[i] == 0:
            i += 1
        if i >= n:
            return
        if blob[i] != 1 or blob[i + 1] != 0:
            raise ValueError(f"bad record framing at offset {i}")
        length = blob[i + 2] | (blob[i + 3] << 8)
        if length < 6 or i + length + 1 > n:
            raise ValueError(f"bad record length {length} at offset {i}")
        rec_type = blob[i + 4]
        payload = bytes(blob[i + 6:i + length])
        i += length + 1
        yield rec_type, payload


def size_arg(s):
    if s.endswith('.'):
        return int(s[:-1], 10)
    if s.startswith(('0o', '0O')):
        return int(s[2:], 8)
    return int(s, 10)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--base", type=lambda s: int(s, 8), default=0,
                    help="octal address of output byte 0 (default 0)")
    ap.add_argument("--size", type=size_arg, default=None,
                    help="pad/check output to exactly this many bytes")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)

    with open(args.input, "rb") as f:
        blob = f.read()

    mem = bytearray()
    txt_count = 0
    last_txt_addr = 0

    def put_word(addr, value):
        off = addr - args.base
        if off < 0 or off + 2 > len(mem):
            sys.exit(f"error: RLD patch at {addr:o} outside image")
        mem[off] = value & 0xFF
        mem[off + 1] = (value >> 8) & 0xFF

    for rec_type, payload in iter_records(blob):
        if rec_type == T_TXT:
            txt_count += 1
            if len(payload) < 2:
                continue
            addr = payload[0] | (payload[1] << 8)
            last_txt_addr = addr
            data = payload[2:]
            if addr < args.base:
                sys.exit(f"error: TXT record at {addr:o} below base {args.base:o}")
            off = addr - args.base
            end = off + len(data)
            if end > len(mem):
                mem.extend(b"\x00" * (end - len(mem)))
            mem[off:end] = data
            if args.debug:
                print(f"  TXT @ {addr:6o}: {len(data)} bytes")
        elif rec_type == T_RLD:
            # Relocation directory: apply fixups to the preceding TXT record.
            # Entry address = last TXT load address + displacement byte - 4.
            # Only the entry types an absolute (.ASECT) build produces are
            # supported; anything global/relocatable is an error here.
            i = 0
            while i + 2 <= len(payload):
                etype = payload[i] & 0x7F
                is_byte = bool(payload[i] & 0x80)
                disp = payload[i + 1]
                addr = last_txt_addr + disp - 4
                if etype == 0o1:      # internal relocation (section base = 0)
                    value = payload[i + 2] | (payload[i + 3] << 8)
                    if is_byte:
                        sys.exit("error: byte-mode internal relocation unsupported")
                    put_word(addr, value)
                    i += 4
                elif etype == 0o3:    # internal displaced (PC-relative)
                    value = payload[i + 2] | (payload[i + 3] << 8)
                    if is_byte:
                        sys.exit("error: byte-mode displaced relocation unsupported")
                    put_word(addr, (value - (addr + 2)) & 0xFFFF)
                    if args.debug:
                        print(f"  RLD displaced @ {addr:6o} -> {value:o}")
                    i += 4
                elif etype == 0o7:    # location counter definition
                    i += 8
                elif etype == 0o10:   # location counter modification
                    i += 4
                elif etype == 0o13:   # program limits
                    i += 2
                else:
                    sys.exit(f"error: unsupported RLD entry type {etype:o} "
                             "(relocatable/global code? this tool links "
                             "absolute .ASECT builds only)")
        elif rec_type == T_ENDMOD:
            break

    if args.size is not None:
        if len(mem) > args.size:
            sys.exit(f"error: image is {len(mem)} bytes, exceeds --size {args.size}")
        mem.extend(b"\x00" * (args.size - len(mem)))

    with open(args.output, "wb") as f:
        f.write(mem)
    print(f"wrote {args.output}: {len(mem)} bytes, {txt_count} TXT record(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
