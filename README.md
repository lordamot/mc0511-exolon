# Exolon for the UKNC (Elektronika MS-0511)

A port of *Exolon* (Hewson, 1987; written by Raffaele Cecco) to the
Soviet UKNC MS-0511 school computer.  The game was reverse-engineered
from the ZX Spectrum tape in this repository (`EXOLON.TAP`) and
re-implemented in MACRO-11 for the UKNC's twin PDP-11 processors: all
125 zones with their original scenery, the collision map that drives
them, Vitorc with the original jump arc and walk cycle, his laser and
grenades, the gun emplacements and rocket banks, the canisters and the
power suit, plus three-voice beeper music and sound effects.

Everything builds from editable text sources into a bootable `.dsk`
image with modern PC-based tools - no vintage software needed.

## Requirements

- Linux, Python 3 with Pillow (`python3 -m pip install pillow`)
- prebuilt tools in `bin/` (MACRO-11 assembler, UKNCBTL-based
  emulators, ZEsarUX for looking at the original); rebuild them from
  source with `make toolchain`

## Build and run

```
make build     # sources -> build/exolon.dsk (bootable image)
make run       # build + play in an SDL window
make shot      # headless: boot to the title screen, screenshot to tmp/
make demo      # headless: start a game, screenshot zone 0
make verify    # resource round-trip against the original, generator
               # determinism, image layout, and a boot-to-gameplay
               # smoke test in the headless emulator
make extract   # re-extract every resource from EXOLON.TAP (destructive)
```

In `make run` the firmware boot menu loads the disk by itself.  The
title screen waits for ENTER or fire.

| Key | Action |
|---|---|
| ← → | walk |
| ↑ | jump |
| ↓ | crouch |
| ФИКС (LCtrl) or space | fire the laser |
| numpad ВВОД (RCtrl) | throw a grenade |
| ENTER | start / confirm |
| СТОП | leave the game |

Walk off the right of a zone to reach the next one.  Gun emplacements,
rocket banks, mines and hoppers all shoot; a laser bolt destroys any of
them, and it also shoots down an incoming missile.  Grenades blow a
hole in solid scenery.  The white canisters refill the laser, the
yellow ones the grenades, and the suit pod turns Vitorc into the
armoured version.

## What is faithful, and what is not

The **content** is the original's, byte for byte: the 125 zone object
lists, the 62 scenery display lists, the 672-glyph tile bank, the
collision classes, the player and 16x16 sprite sheets and the three
music streams are all extracted from the tape.  `make verify` renders
every zone twice - once by interpreting the original's data structures
straight out of `EXOLON.TAP`, once from the editable resources through
the port's own interpreter - and requires the two to agree cell for
cell.

The **engine** is a re-implementation rather than a transliteration,
but the parts that decide how the game feels were taken from the Z80
code: the 22-entry jump arc table, the 10-frame walk cycle, walking at
one 2-pixel unit a frame, and the collision rules - walls tested only
when x sits on a cell boundary, the floor only when y does, and the
last few columns of a zone always passable so scenery cannot trap you.
See `.claude/docs/re-notes.md` for where each of those lives in the
original.

## The machine, and what it does to the graphics

The UKNC has two PDP-11 processors.  The CPU runs the game engine; a
PPU program (loaded over channel K2 at startup) owns the video line
table, the keyboard, the vsync exchange and - in its idle loop - the
beeper sound engine.

The CPU can only reach video planes 1 and 2, which gives four pixel
values per cell.  Every 8-line cell row, though, carries its own
palette element, so each row shows black plus **three inks chosen from
the full 16-colour palette**, and each cell picks one of the three
independently - there is no attribute clash inside a row.  The port
uses that at zone load: `zone.mac` weighs every ink in a row by how
many pixels it lights, keeps the three heaviest, and snaps the rest to
the nearest survivor.  The result is very close to the Spectrum
original (compare `make demo` with `tools/zone_render.py 0 out.png`),
and where the Spectrum had to spend both of a cell's colours the port
does not.

Sprites are drawn in the slot whose ink is nearest white, and a
playfield row whose third ink is only a detail colour hands that slot
to white outright, so Vitorc stays white almost everywhere without
costing the scenery a colour.  Sky rows are left alone entirely, which
is why the planets keep their own inks.

The beeper is a single bit (bit 7 of PPU port 177716).  The music
engine gives each of three voices a 16-bit phase accumulator, adds its
increment once per pass of the idle loop and flips the speaker on the
carry: three square waves XORed onto one output, with the pitch exact
to a fraction of a hertz.  The tune is Exolon's own - the 128K release
carried an AY score that the 48K one never played, and
`tools/music_extract.py` decodes its three streams out of the tape.

## Project layout

| Path | Contents |
|---|---|
| `src/*.mac` | MACRO-11 sources (CPU game engine + PPU program) |
| `src/exolon.list` | module order = memory order of the image |
| `src/res/` | editable resources: tiles, display lists, zones, sprites, strings, music |
| `tools/` | build pipeline, resource generators, RE tools, emulator drivers |
| `bin/` | prebuilt assembler and emulators |
| `build/` | build products (not committed) |
| `.claude/docs/` | reverse-engineering notes and port design |

## Tools

| Tool | What it does |
|---|---|
| `build_exolon.py` | the whole build: generators, assemble, link, disk |
| `extract_res.py` | tape -> `src/res/` (one-time bootstrap) |
| `exolon_re.py` | the RE library: tape image, the original's display-list interpreter, zone tables |
| `resources.py` | readers for the editable resources, shared by the generators |
| `zone_render.py` | render a zone (or a contact sheet) from the resources, in ZX or UKNC colours |
| `tiles_gen.py` `objects_gen.py` `zones_gen.py` `sprites_gen.py` `text_gen.py` `music_gen.py` | resource -> MACRO-11 |
| `music_extract.py` | decode the original's three AY streams into `res/music/title.txt` |
| `obj2bin.py` `dsk_build.py` | link a flat image, lay out the raw disk |
| `uknc_control.py` | drive the headless UKNC emulator (boot, keys, screenshots, memory dumps, audio capture) |
| `zx_control.py` | drive ZEsarUX on the original tape (keys, screenshots, memory dumps) |
| `tap_extract.py` `z80dis.py` `z80_disasm.py` `z80_trace.py` `zx_view.py` | the ZX side: tape blocks, disassembly, code/data tracing, graphics viewing |
| `verify_build.py` | the checks behind `make verify` |
| `build_toolchain.py` | rebuild `bin/` from source |

Resources are the source of truth.  Edit `src/res/zones/zones.txt`
(one `<row> <col> <object>` line per placement),
`src/res/objects/objects.txt` (the scenery byte code, one mnemonic per
line), `src/res/tiles/tiles.txt` (`#` bitmaps),
`src/res/sprites/*.txt` or `src/res/music/title.txt` and rebuild.
`make extract` regenerates them from the tape and overwrites local
edits, including the laser and grenade sprites added by hand as frames
45 and 46 of `small.txt`.

## Credits

- Original game: Raffaele Cecco / Hewson Consultants, 1987.  This is a
  non-commercial preservation and porting project; the original game
  content belongs to its rights holders.
- Emulator core: [UKNCBTL](https://github.com/nzeemin/ukncbtl-qt)
  (LGPL), used for the bundled headless test runner and player.
- MACRO-11 assembler: Richard Krehbiel's `macro11` (see
  `bin/macro11/LICENSE`).
- ZEsarUX (GPL) for driving the original ZX Spectrum game.
