#!/usr/bin/env python3
"""build_toolchain.py - (re)build the cross toolchain into bin/.

Everything compiles under tmp/ and only the results are installed into
bin/, per the project guideline.  Two components:

  macro11        Richard Krehbiel's portable MACRO-11 assembler
                 (the shattered/macro11 fork) + this project's two
                 crash fixes from tools/macro11-src/*.patch.
                 Source: cloned from github, or copied from
                 ../mc0511test/toolchain if the clone is unreachable.

  uknc-headless  scriptable UKNC emulator runner for automated tests,
  uknc-play      and the interactive SDL2 player window (`make run`),
                 both built from tools/uknc-headless/ sources against
                 the emubase core of nzeemin/ukncbtl-qt (LGPL).  The
                 32 KB uknc_rom.bin firmware image comes from the same
                 repo; the player links against the host's SDL2
                 runtime library (no dev package needed).

Usage:
    python3 tools/build_toolchain.py [--only macro11|headless]
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TMP = REPO_ROOT / "tmp"
MACRO11_REPO = "https://github.com/shattered/macro11"
UKNCBTL_REPO = "https://github.com/nzeemin/ukncbtl-qt.git"
MACRO11_FALLBACK = REPO_ROOT.parent / "mc0511test/toolchain"


def run(argv, cwd, fail):
    r = subprocess.run(argv, cwd=cwd)
    if r.returncode != 0:
        sys.exit(f"error: {fail}")


def build_macro11():
    src = TMP / "macro11-src"
    if not (src / "macro11.c").exists():
        if shutil.which("git"):
            r = subprocess.run(["git", "clone", "--depth", "1",
                                MACRO11_REPO, str(src)])
            cloned = r.returncode == 0
        else:
            cloned = False
        if not cloned:
            if not (MACRO11_FALLBACK / "macro11.c").exists():
                sys.exit("error: cannot clone macro11 and no local copy at "
                         f"{MACRO11_FALLBACK}")
            shutil.copytree(MACRO11_FALLBACK, src, dirs_exist_ok=True)
        for patch in sorted((REPO_ROOT / "tools/macro11-src").glob("*.patch")):
            r = subprocess.run(["patch", "-p0", "--forward", "-d", str(src),
                               "-i", str(patch)])
            if r.returncode != 0:
                print(f"note: {patch.name} did not apply cleanly "
                      "(possibly already applied)")
    run(["make"], src, "macro11 build failed")
    dest = REPO_ROOT / "bin/macro11"
    dest.mkdir(parents=True, exist_ok=True)
    for f in ("macro11", "dumpobj"):
        shutil.copy2(src / f, dest / f)
    if (src / "LICENSE").exists():
        shutil.copy2(src / "LICENSE", dest / "LICENSE")
    print(f"installed {dest}/macro11")


def build_headless():
    emu = TMP / "ukncbtl-qt"
    if not (emu / "emulator/emubase/Board.cpp").exists():
        run(["git", "clone", "--depth", "1", UKNCBTL_REPO, str(emu)],
            REPO_ROOT, "cannot clone ukncbtl-qt (network?)")
    work = TMP / "uknc-headless"
    work.mkdir(parents=True, exist_ok=True)
    for f in ("main.cpp", "uknc-play.cpp", "stdafx.h", "sdl2_min.h",
              "Makefile"):
        shutil.copy2(REPO_ROOT / "tools/uknc-headless" / f, work / f)
    run(["make"], work, "uknc-headless build failed")
    dest = REPO_ROOT / "bin/ukncbtl"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(work / "uknc-headless", dest / "uknc-headless")
    shutil.copy2(work / "uknc-play", dest / "uknc-play")
    shutil.copy2(emu / "emulator/uknc_rom.bin", dest / "uknc_rom.bin")
    shutil.copy2(emu / "LICENSE", dest / "LICENSE")
    print(f"installed {dest}/uknc-headless")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", choices=["macro11", "headless"])
    args = ap.parse_args(argv)
    TMP.mkdir(exist_ok=True)
    if args.only in (None, "macro11"):
        build_macro11()
    if args.only in (None, "headless"):
        build_headless()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
