#!/usr/bin/env python3
"""dsk_build.py - build a raw UKNC bootable .dsk image from a manifest.

The game disk has no file system: the boot sector (LBA 0) is the first
sector of the main program, and everything else is addressed by absolute
LBA sector numbers hard-coded in the loader's parameter blocks (see
src/boot/boot.mac).  The disk is a plain sector-by-sector image:
80 tracks x 2 sides x 10 sectors x 512 bytes = 819200 bytes.

Manifest (JSON):
    {
      "geometry": {"size": 819200},
      "entries": [
        {"file": "open60.raw", "lba": 0,  "sectors": 32},
        {"file": "greybw.out", "lba": 32, "sectors": 11},
        ...
      ]
    }

"file" paths are relative to the manifest's directory.  "lba" is the
sector where the file starts (optional: default is right after the
previous entry).  "sectors" is the reserved length (optional: default
is the file size rounded up); the file must fit.  Gaps and the tail are
zero-filled.

Usage:
    python3 dsk_build.py MANIFEST.json OUTPUT.dsk [--force]
"""

import argparse
import json
import sys
from pathlib import Path

SECTOR = 512


def build(manifest_path, output_path, force=False):
    manifest_path = Path(manifest_path)
    output_path = Path(output_path)
    if output_path.exists() and not force:
        sys.exit(f"error: {output_path} exists (use --force to overwrite)")

    with open(manifest_path) as f:
        manifest = json.load(f)

    size = manifest.get("geometry", {}).get("size", 819200)
    image = bytearray(size)
    next_lba = 0

    for entry in manifest["entries"]:
        path = manifest_path.parent / entry["file"]
        data = path.read_bytes()
        lba = entry.get("lba", next_lba)
        sectors = entry.get("sectors", (len(data) + SECTOR - 1) // SECTOR)
        if len(data) > sectors * SECTOR:
            sys.exit(f"error: {path.name} is {len(data)} bytes, "
                     f"exceeds its {sectors}-sector budget "
                     f"({sectors * SECTOR} bytes)")
        start = lba * SECTOR
        end = start + sectors * SECTOR
        if end > size:
            sys.exit(f"error: {path.name} at LBA {lba} runs past the disk end")
        if any(image[start:start + len(data)]):
            sys.exit(f"error: {path.name} at LBA {lba} overlaps a previous entry")
        image[start:start + len(data)] = data
        print(f"  LBA {lba:4d} +{sectors:3d}  {path.name}  ({len(data)} bytes)")
        next_lba = lba + sectors

    output_path.write_bytes(image)
    print(f"wrote {output_path}: {size} bytes")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest")
    ap.add_argument("output")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    build(args.manifest, args.output, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
