# Exolon for the UKNC (Elektronika MS-0511)

A port of *Exolon* (Hewson, 1987; written by Raffaele Cecco) to the
Soviet UKNC MS-0511 school computer.  The game was reverse-engineered
from the ZX Spectrum tape in this repository (`EXOLON.TAP`) and
re-implemented in MACRO-11 for the UKNC's twin PDP-11 processors: all
125 zones with their original scenery, the collision map that drives
them, Vitorc with the original jump arc and walk cycle, his laser and
grenades, the gun emplacements and their recoil, the force fields'
energy balls, the mines' homing missiles, the canisters and the power
suit, plus three-voice beeper music and sound effects.

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

In `make run` the firmware boot menu loads the disk by itself (the disk
answers to the name `EXOLON`).  The title screen carries the original's
numbered options and one more:

| Key | Action |
|---|---|
| 1 | start the game |
| 2 | infinite lives on / off |
| 3 | start from a chosen zone - pick it with ↑ / ↓ while the option is on |

and in play:

| Key | Action |
|---|---|
| ← → | walk - Vitorc turns to face the way he is going |
| ↑ | jump; in a teleport booth or a suit booth, use it |
| ↓ | crouch - a gun emplacement's shot passes over you |
| ФИКС (LCtrl) or space | fire - one bolt, or two in the power suit |
| numpad ВВОД (RCtrl) | throw a grenade |
| АП2 | pause |
| СТОП | leave the game |

Walk off the right of a zone to reach the next one.  Gun emplacements
fire down their own row - always to the left, the side you come from -
and rock back as they do; crouch and the shot goes over your head.  The
guns bolted to the walls, singly and in pairs, spit along their own row
at you as you come; force fields fill their rings with energy balls
that swirl about and kill on contact - and where a pair of pylons
stands with nothing between it, the balls drift loose; and mines throw
a missile in from the right that comes down to your own height, over
and over, until you blow the mine up with a grenade.

The scenery is alive the way the original's is.  Jet flames flicker
under the hovering platforms, the parked spaceships and the pods; the
teleport booths shimmer through their colours; energy arcs crackle
between pylon pairs.  Land mines sit armed in the floor and go off
underfoot, then burn for the rest of your visit; pumps rise out of the
floor, hold, and sink back, and touching one while it cycles is fatal;
under some hovering platforms a colour-cycling **laser beam** reaches
to the ground - walk into it and die, or cut it down with twenty-five
laser bolts.  The power suit walks over mines and pumps unharmed, as
on the Spectrum.  And seventy of the 125 zones send **flyers** after
you - spheres, saucers and spinners on the original's six byte-coded
paths, four-frame animated, each worth points to shoot down and fatal
to the touch.

A laser bolt shoots down what is in the air - the enemy fire, the
flyers, the energy balls - and against anything that stands on the
ground it just bursts in a spark, as on the Spectrum.  The gun
emplacements, the rock formations that block the way out of a zone,
the mines, dishes, hoppers and every other piece of standing scenery
need a **grenade** - in the original the bolt only ever dies on the
solid map, and 0x93E2 lets the grenade take out exactly one object.  The
grenade is a lob, not a blast: it leaves your shoulder climbing, flies
level trailing smoke, then dives, and it destroys the one thing it
lands on.  It has a range, so judge the distance - thrown from too far
back it is in the ground before it arrives.  Whatever you blow up, the
explosion itself cannot hurt you.

The pistol fires the original's six-pixel dash (the 0xBD pattern of
0x82FC), and it goes where you are looking: a wall gun's two barrels
are two separate targets, and standing you can only cut down the upper
stream and crouched only the lower.  The **power suit** is worth
finding for more than the free hit it absorbs - it fires from two
barrels six pixels apart, as the original's does, and that takes down
both streams at once.

The white canisters refill the laser and the yellow ones the grenades:
walk into them.  Standing in a teleport booth and pressing the up arrow
moves Vitorc to the booth's other pad in a shower of sparks, and the
same key in a power-suit booth puts the armour on.

**Do not loiter.**  Stay in one zone for fourteen seconds and a rocket
comes in from the right at your height, trailing smoke, and it does not
miss twice.

Every 25th zone - 24, 49, 74, 99 and 124 - ends its level at a **gate**
between two tall pylons.  Reach it and the end-of-level ceremony runs
as on the Spectrum: a framed window totals your LIVES BONUS (1000 a
life, paid at once) and - if you arrive without the power suit - a
BRAVERY BONUS of 10000, ticked onto the score in eighty steps; the
last gate adds its CONGRATULATIONS screen.  Then the EXOLON BONUS
SCREEN appears: a pointer sweeps down a ladder of eight prize rows,
fire stops it, and only the odd rows pay - 1000, 3000, 5000 or 7000.
The pointer's counter keeps running from one gate to the next, so the
row it lands on is anyone's guess.  You leave with an extra life (nine
at most), the suit off, everything refilled, at the next level's first
zone.

## What is faithful, and what is not

The **content** is the original's, byte for byte: the 125 zone object
lists, the 62 scenery display lists, the 684-glyph tile bank, the
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
So were the timings and tables behind everything that moves: the
grenade's 32-step arc and the three-updates-a-frame it switches to
half-way through, the emplacement's one-in-forty random trigger and the
eight tile pairs of its recoil, the ten-frame spark and the twenty-
frame shower each teleport pad throws, the energy balls' one-in-seven
random turn, the mine's relaunch-at-a-random-height, and the 700 frames
you have in a zone before a rocket is sent after you.

The collision classes a display list writes follow the original's own
solid/passable split (its table at 0x8EF4), so the frame of a teleport
booth is walked through while its pad is not, and the teleport and the
power suit are worked with the up arrow exactly as on the Spectrum.
See `.claude/docs/re-notes.md` for where each of those lives in the
original.

Four things are deliberately **not** the original.  Everything faces
the way it is going: the Spectrum sheet holds one facing for the player
and its plotter cannot mirror, so there Vitorc walks left backwards,
and the rocket that hunts a lingering player is drawn from a
right-facing frame although it only ever flies left - the port reverses
those lines through a lookup table instead.  The power suit is a
weapon as well as armour, with its two guns and their heavier bolt,
where the original's only absorbed a hit.  A force field emits
six energy balls rather than eight, because on this machine a moving
sprite costs several times what the Spectrum's XOR plotter did, the
balls all swirl inside the ring's two cells and overlap into one blob
anyway, and the two extra would have cost a fifth of the frame rate in
those zones.  And the title screen's second option is infinite lives
rather than REDEFINE KEYS, which a machine with one keyboard layout
does not need.

The other departure is invisible: `RANDOM` is a 16-bit LCG rather than
the Z80 refresh register the original reads, because almost every timer
in the game is "fire when a random byte clears a threshold" sampled
once a frame, and a generator whose consecutive bytes are correlated
turns those into bursts.

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

Sprites are drawn in the slot whose ink is nearest white, and every
playfield row hands its third slot - the least used of the three - to
white, so Vitorc is white wherever he can walk or jump.  Without that
he changes colour halfway up a jump, in whatever row happens to have
three heavy inks.  Sky rows only give the slot up when their third ink
is a detail colour, which is why the planets keep their own inks.

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
| `obj2bin.py` `dsk_build.py` `rt11_home.py` | link a flat image, lay out the raw disk, give it its name |
| `uknc_control.py` | drive the headless UKNC emulator (boot, keys, screenshots, memory dumps, audio capture) |
| `zx_control.py` | drive ZEsarUX on the original tape (keys, screenshots, memory dumps) |
| `tap_extract.py` `z80dis.py` `z80_disasm.py` `z80_trace.py` `zx_view.py` | the ZX side: tape blocks, disassembly, code/data tracing, graphics viewing |
| `verify_build.py` | the checks behind `make verify`, scripted runs of the title screen and of gameplay included (the menu's two options, facing, the grenade's arc, the emplacement recoil, the teleport shower, energy balls, wall guns, mine missiles, the lingering-player rocket, and what each gun can and cannot shoot down) |
| `build_toolchain.py` | rebuild `bin/` from source |

Resources are the source of truth.  Edit `src/res/zones/zones.txt`
(one `<row> <col> <object>` line per placement),
`src/res/objects/objects.txt` (the scenery byte code, one mnemonic per
line), `src/res/tiles/tiles.txt` (`#` bitmaps),
`src/res/sprites/*.txt` or `src/res/music/title.txt` and rebuild.
`make extract` regenerates them from the tape, including frames
46..52, which are the grenade, the energy ball, the three sparks and a
wall gun's shot, copied in from the original's *second*, 16x8 sprite
bank at 0xED40 - the port has one sprite format where the Spectrum had
two - and frame 57, the laser bolt's dash, which the original drew as
a bare bit pattern and never kept as a sprite.

## Credits

- Original game: Raffaele Cecco / Hewson Consultants, 1987.  This is a
  non-commercial preservation and porting project; the original game
  content belongs to its rights holders.
- Emulator core: [UKNCBTL](https://github.com/nzeemin/ukncbtl-qt)
  (LGPL), used for the bundled headless test runner and player.
- MACRO-11 assembler: Richard Krehbiel's `macro11` (see
  `bin/macro11/LICENSE`).
- ZEsarUX (GPL) for driving the original ZX Spectrum game.
