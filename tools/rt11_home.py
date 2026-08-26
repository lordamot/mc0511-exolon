#!/usr/bin/env python3
"""rt11_home.py - write an RT-11 home block, so the disk has a name.

    rt11_home.py OUT.bin [--volume EXOLON] [--owner NAME] [--force]

Block 1 of a PDP-11 floppy is the home block, and its volume
identification field is what disk tools, catalogue utilities and other
emulators call the disk's name.  The game disk is a raw bootable image
with no directory - the program starts at block 2 and the boot sector
addresses it by absolute LBA - so this block carries the label and the
standard shape around it, and nothing else.

Layout (octal byte offsets into the 512-byte block), as RT-11 defines
it and as the reference volume in mc0511test/toolchain/rt11.dsk has it:

    0722  pack cluster size (1)
    0724  block number of the first directory segment (6)
    0726  system version, RAD50 "V3A"
    0730  volume identification, 12 bytes
    0744  owner name, 12 bytes
    0760  system identification, 12 bytes
    0776  checksum (RT-11 itself leaves this zero)
"""

import argparse
import sys
from pathlib import Path

BLOCK = 512
OFF_CLUSTER = 0o722
OFF_DIRSEG = 0o724
OFF_VERSION = 0o726
OFF_VOLUME = 0o730
OFF_OWNER = 0o744
OFF_SYSTEM = 0o760
FIELD = 12
SYSTEM_ID = "DECRT11A"
VERSION = 0o107123              # RAD50 "V3A"


def field(text, name):
    text = text.upper()
    if len(text) > FIELD:
        sys.exit(f"error: {name} {text!r} is longer than {FIELD} characters")
    for ch in text:
        if not (32 <= ord(ch) < 127):
            sys.exit(f"error: {name}: {ch!r} is not printable ASCII")
    return text.ljust(FIELD).encode("ascii")


def home_block(volume, owner=""):
    b = bytearray(BLOCK)

    def word(off, val):
        b[off] = val & 0xFF
        b[off + 1] = (val >> 8) & 0xFF

    word(OFF_CLUSTER, 1)
    word(OFF_DIRSEG, 6)
    word(OFF_VERSION, VERSION)
    b[OFF_VOLUME:OFF_VOLUME + FIELD] = field(volume, "volume id")
    b[OFF_OWNER:OFF_OWNER + FIELD] = field(owner, "owner name")
    b[OFF_SYSTEM:OFF_SYSTEM + FIELD] = field(SYSTEM_ID, "system id")
    return bytes(b)


def read_volume(block):
    """The name out of a home block (or the second block of an image)."""
    return block[OFF_VOLUME:OFF_VOLUME + FIELD].decode("ascii",
                                                       "replace").strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("output")
    ap.add_argument("--volume", default="EXOLON")
    ap.add_argument("--owner", default="")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.output)
    if out.exists() and not a.force:
        sys.exit(f"error: {out} exists (use --force)")
    out.write_bytes(home_block(a.volume, a.owner))
    print(f"wrote {out}: home block, volume {a.volume.upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
