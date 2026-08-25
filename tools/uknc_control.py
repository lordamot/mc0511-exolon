#!/usr/bin/env python3
"""uknc_control.py - drive the headless UKNC emulator (bin/ukncbtl).

A convenience wrapper over bin/ukncbtl/uknc-headless: it writes the
low-level script (power-up, boot-from-floppy menu, key presses,
screenshots) and runs the emulator for you.  Screenshots are converted
to PNG when Pillow is available.

Usage:
    python3 tools/uknc_control.py boot [--disk build/brucelee.dsk]
        [--wait N] [--shot tmp/shot.png]
    python3 tools/uknc_control.py play [--disk ...] KEY [KEY ...]
        [--wait N] [--shot tmp/shot.png] [--every N]
    python3 tools/uknc_control.py script FILE.script
    python3 tools/uknc_control.py keys

`boot` powers the machine, picks "1 - диск" in the firmware loader and
waits for the game menu.  `play` does the same, then presses the given
keys (~0.5 s apart) and takes a final screenshot.  `script` runs a raw
uknc-headless script (see bin/ukncbtl/uknc-headless source for the
command set).  `keys` lists the key names.

Key names (or a raw octal UKNC scancode):
    UP DOWN LEFT RIGHT ENTER FIRE1 FIRE2 AP2 STOP SPACE 0..9
FIRE1 is ФИКС (player 1 open), FIRE2 is numpad ВВОД (player 2 open),
AP2/STOP open the in-game menu.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EMU = REPO_ROOT / "bin/ukncbtl/uknc-headless"
ROM = REPO_ROOT / "bin/ukncbtl/uknc_rom.bin"

KEYS = {
    "UP": "154", "DOWN": "134", "LEFT": "116", "RIGHT": "133",
    "ENTER": "153", "FIRE1": "107", "FIRE2": "166",
    "AP2": "006", "STOP": "004", "SPACE": "113",
    "0": "176", "1": "030", "2": "031", "3": "032", "4": "013",
    "5": "034", "6": "035", "7": "016", "8": "017", "9": "177",
}


def keycode(name):
    name = name.upper()
    if name in KEYS:
        return KEYS[name]
    if all(c in "01234567" for c in name):
        return name
    sys.exit(f"error: unknown key {name!r} (try: {' '.join(KEYS)})")


def boot_preamble():
    # power-up self test, then "1" + ENTER in the firmware loader menu,
    # then the boot sector + program + title data load; the title
    # picture times out by itself (load time varies with the FDD
    # rotation phase, so waiting is more robust than a skip press)
    return ["run 900", "press 030", "run 30", "press 153", "run 1000"]


def run_script(disk, lines, shots):
    with tempfile.NamedTemporaryFile("w", suffix=".script",
                                     delete=False) as f:
        f.write("\n".join(lines) + "\nquit\n")
        path = f.name
    r = subprocess.run([str(EMU), "--rom", str(ROM),
                        "--disk", str(disk), "--script", path])
    Path(path).unlink()
    if r.returncode != 0:
        sys.exit("error: emulator run failed")
    try:
        from PIL import Image
    except ImportError:
        return
    for bmp, png in shots:
        Image.open(bmp).save(png)
        Path(bmp).unlink()
        print(f"screenshot: {png}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["boot", "play", "script", "keys"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--disk", default="build/brucelee.dsk")
    ap.add_argument("--wait", type=int, default=100,
                    help="extra frames to run at the end")
    ap.add_argument("--shot", default=None, help="final screenshot PNG path")
    ap.add_argument("--every", type=int, default=25,
                    help="frames between key presses in `play`")
    args = ap.parse_args(argv)

    if args.command == "keys":
        for k, v in KEYS.items():
            print(f"{k:6s} {v}")
        return 0

    disk = Path(args.disk)
    if not disk.is_absolute():
        disk = REPO_ROOT / disk
    if not disk.exists():
        sys.exit(f"error: disk image {disk} not found (make build?)")
    if not EMU.exists():
        sys.exit("error: bin/ukncbtl/uknc-headless not built "
                 "(run: python3 tools/build_toolchain.py)")

    shots = []
    if args.command == "script":
        if not args.args:
            sys.exit("error: script FILE required")
        r = subprocess.run([str(EMU), "--rom", str(ROM),
                            "--disk", str(disk),
                            "--script", args.args[0]])
        return r.returncode

    lines = boot_preamble()
    if args.command == "play":
        for key in args.args:
            lines.append(f"press {keycode(key)}")
            lines.append(f"run {args.every}")
    lines.append(f"run {args.wait}")
    if args.shot:
        png = Path(args.shot)
        bmp = png.with_suffix(".bmp")
        lines.append(f"screenshot {bmp}")
        shots.append((bmp, png))
    run_script(disk, lines, shots)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
