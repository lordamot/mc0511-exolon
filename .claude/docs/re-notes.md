# Reverse-engineering notes: EXOLON.TAP (ZX Spectrum, Hewson 1987)

*Exolon*, by Raffaele Cecco.  Everything below was recovered from the
tape in this repo with the tools in `tools/` and checked against the
running game in ZEsarUX (`tools/zx_control.py`).  Addresses are ZX
memory-map addresses.

## Tape structure (tools/tap_extract.py)

| Block | Header | Loads at | Content |
|---|---|---|---|
| 0/1 | Program `exolon` | BASIC | `CLEAR 25999`, `LOAD ""CODE`, pokes, `RANDOMIZE USR 65082` |
| 2/3 | Bytes `exolon` 768 | 0xFC00 | self-decrypting custom tape loader |
| 4/5 | type 42, 4096 | 0x8000 | loading-screen decompressor + packed picture |
| 6/7 | type 42, 37536 | **0x6D60** | the whole game, up to 0xFFFF |

The type-42 headers are still ROM-format blocks, so ZEsarUX's tape
traps load them; the `p1` field (26000 = the `CLEAR` value) is *not*
the load address.  Correlating the block against a live memory dump
gives 0x6D60, and 0x6D60 + 37536 = 0x10000 exactly - the game fills
RAM to the top.  `tools/exolon_re.py:load_image()` rebuilds the image
from the tape alone; only 261 bytes differ from a live dump (runtime
variables), so the tape image is the source of truth.

Entry point is 0x6D60 (`DI / LD SP,0`).  `LD A,(0x386E); SUB 0xFF;
LD (0x6E16),A` is the **48K/128K detection**: on a 48K ROM the result
is 0, which enables the beeper routines; a 128K machine uses the AY
driver instead.  Our port follows the 48K path plus the AY tune data.

## Memory map

| Range | What |
|---|---|
| 0x4000-0x5AFF | screen |
| 0x5800-0x5AFF | attributes |
| 0x5B00-0x5DFF | "hit" cell map (0xFF where a sprite/beam has drawn) |
| 0x5E00-0x60FF | sprite-occupancy cell map |
| 0x6100-0x63FF | **solid cell map** (per cell: 0 = empty, else scenery class) |
| 0x6D60-0x7FFF | game code (start, menu, keys, sprite plotters, beeper) |
| 0x8000-0xB180 | game code (player, bullets, enemies, HUD, zone loader) |
| 0xB181-0xB6D0 | work buffer (cleared per zone) |
| 0xB6EC-0xBA00 | AY music player (3 channels) |
| 0xBA01-0xBF6C | AY music data: streams 0xBA01, 0xBB7E, 0xBD06 |
| 0xBF6D-0xC218 | AY output + SFX triggers |
| 0xC280-0xC5E6 | SFX definitions |
| 0xC5EB-0xC6EA | 16 x 16-byte AY sound slots |
| 0xC6EB.. | AY envelope tables; 0xC71B = note -> AY period table |
| 0xC7F4-0xC8ED | **zone pointer table**, 125 words |
| 0xC8EE-0xD8DF | **zone data**: {row, col, object} triples, 0xFF-terminated |
| 0xD7E0-0xDAB7 | 8x8 font (ASCII from space) |
| 0xD8E0-0xECDF | 8x8 scenery tiles (484 distinct tiles are actually used) |
| 0xEF80-0xF8DF | **player sprites**: 25 frames of 3x32 bytes (24x32 px) |
| 0xF8E0-0xFFFF | **16x16 sprites**: 57 frames of 2x16 bytes |
| 0x852E-0x85A9 | **object display-list table**, 62 words |
| 0x85AA-0x8DDD | the 62 scenery display lists |
| 0x94C6.. | object bounding boxes, 5 bytes each, bit 7 of byte 0 ends |

## Coordinates

Everything uses `D` = pixel row (0..191) and `E` = **x in 2-pixel
units** (0..127).  `0x9936` converts a cell position to that form
(E*4, D*8).  The cell of (D,E) is `row = D>>3`, `col = E>>2`
(`0x80A8` / `0x80C1` / `0x80DA` build the three cell-map addresses).

## The scenery display lists (interpreter at 0xAF2B)

All scenery is painted by a byte-code interpreter over a cursor
(D = cell row, E = cell column) with a current attribute byte C.
`tools/exolon_re.py:ListRunner` is a faithful re-implementation; it
reproduces the original screens exactly.

    00..60   draw tile A at (D,E) from the current tile base; E += 1
    61..8F   D += op-0x78; E += next byte      (relative cursor move)
    90..CE   D += 1; E += op-0xAF              (newline + column delta)
    CF..DE   ink = op-0xCF (>=8 -> +BRIGHT), paper bits of C kept
    DF a b   cursor D=a, E=b
    E0 a     attribute C = a
    E1 n     start of a block repeated n times
    E2       end of block
    E3 lo hi call a sub-list
    E4 n t   draw tile t, n times to the right
    E5 n t   draw tile t, n times downwards
    E6 lo hi set the tile graphics base
    E7       draw tile 0x20 from base 0xD7E0 (a one-off)
    E8 n     value stored into the solid map for each drawn cell
    E9 / EA  value stored into the hit map (0 / 0xFF)
    EB n     animation hook (no effect on a still frame)
    other    end of list

The plotter (0xADE1) drops any cell whose column is outside 0..31
(`BIT 5,E; RET NZ`), which is how objects hang off the screen edges;
zone entries with a column >= 0x80 are negative (partly off-screen at
the left).

## Zone data

`zone = 0x8523` (0..124).  The loader at 0x8485 runs once whenever
0x82F2 is set, walks the zone's triple list, and for each triple:

- `0x9487` looks the object up in the box table at 0x94C6 and, when it
  is there, appends a 7-byte record {x0, x1, y0, y1, col, row, object}
  to the live object list at 0x9437 (0xFF-terminated) - this is the
  list the player and bullets collide against;
- the object's display list (table 0x852E) is run with solid = 1 and
  hit = 0 at the triple's (row, col).

Objects that have a box (and so are "live"): 5, 13, 15, 16, 18, 21,
31, 40, 44, 46.  Objects 18/19 share a list and are the **ammo
canister** (0x9942: refills ammo to 99 and erases the canister with
the list at 0x887E); object 20 is the **grenade canister** (refills
grenades to 10, erase list at 0x888F).

## Player

| Address | Meaning |
|---|---|
| 0x82F3/F4 | zone-entry X/Y (restart position) |
| 0x82F5 | player X, 2-pixel units |
| 0x82F6 | player Y, pixels |
| 0x82F7 | jump counter, 0x16..0 |
| 0x82F8 | horizontal step this frame (+1 / -1 / 0) |
| 0x82F9 | walk animation counter 0..9 |
| 0x82FA | facing (+1 right, 0xFF left) |
| 0x82FB | duck flag (0xFA when airborne) |
| 0x8523 | zone number |
| 0x8E5A | ammo (starts 0x63 = 99) |
| 0x8E66 | grenades (starts 0x0A = 10) |
| 0x8E7A | lives (starts 9 in the code; the HUD shows 0x8E7A) |
| 0x9ED8 | power-suit frame offset (0 = no suit) |

Walk speed is 1 unit (2 px) per frame.  The **jump arc** is a table of
per-frame dy at 0x826A, read with the counter 0x82F7 counting down
from 22:

    -4 -4 -2 -2 -2 -1 -1 -1 -1  0  0  0  0 +1 +1 +1 +1 +2 +2 +2 +4 +4

18 px up, four frames of hang, 18 px down, 22 frames total.  While dy
is negative the ceiling test (0x8179) runs, otherwise the floor test
(0x814E).  Walking off the right edge (X >= 0x80 at 0x822B) advances
the zone (0x8253: Y and X are latched as the new entry point and
0x82F2 is set).

Player frames (0xEF80 + n*96, 24x32 px, four pre-shifted plotters
selected by `E & 3` - 0x76DA):

| Frame | Pose |
|---|---|
| 0..9 | walk cycle (0x82F9) |
| 10 | crouch |
| 11 | death |
| 12..21 | the same walk cycle in the power suit |
| 22 | suit crouch |
| 23 | suit death |
| 24 | ground cannon |

Standing uses frame 5, jumping frame 3.  The 16x16 set (0xF8E0 +
n*32, plotter 0x795C) holds explosions (0..9), missiles and rockets
(10..15), energy balls (16..19) and the rest of the moving objects.

## Bullets

List of 3-byte records {E, D, step} at 0x845F, updated at 0x83DD and
spawned at 0x8391.  The muzzle offset is +14 px in Y standing (+19
ducking) and +12 / -4 units in X depending on facing.  A bullet dies
64 units to the right of the player or 52 to the left, or on hitting
the solid map / an object.  Firing decrements ammo (0x8E5A).  Bullets
are drawn by 0x82FC as a 16-bit pattern (0x00BD) shifted by
`(~E & 3) + 1` double-pixels and XORed onto the screen - 2-pixel
horizontal resolution.

## Death

0x9CAA: sets a 46-frame death counter (0x9CE2) and plays the arc at
0x9D4A (the same shape as the jump table, run once), then respawns at
(0x82F3, 0x82F4) with ammo and grenades refilled and one life gone;
at zero lives it goes to game over (0xA02A).

## Sound

The 48K path uses two beeper routines, both gated on 0x6E16 == 0:

- `0x7C26` - noise burst, `LD A,R / OUT (0xFE)` with a `B`-length
  inner delay (explosions, hits);
- `0x7C3C` - a downward frequency sweep (pickups, teleport).

The 128K path drives an AY through 0xBF6D.  Its **music** is worth
having: a 3-channel player at 0xB6EC with streams at 0xBA01, 0xBB7E
and 0xBD06 and a note -> period table at 0xC71B.  Stream commands:

    00..31   note number (0 = rest), duration = the channel default
    32..63   note (op-0x32) with an explicit duration byte following
    64       toggle the mixer bits with (ix+11)
    65..74   set the volume floor to op-0x65
    75 lo hi call a sub-sequence
    76       return from a sub-sequence
    77 n     transpose by n
    78 lo hi jump (loop)
    79 n     set the AY noise period
    89 n..   per-channel vibrato limit
    8A n..   per-channel envelope limit
    FF       end of tune

`tools/music_extract.py` decodes the three streams into note/duration
events for the UKNC beeper player.

## Emulator driving (tools/zx_control.py)

    zx_control.py launch --tap EXOLON.TAP --machine 48k \
        --romfile /usr/share/spectrum-roms/48.rom
    zx_control.py press J SYM_SHIFT+P SYM_SHIFT+P ENTER   # LOAD ""
    zx_control.py press 5      # Kempston
    zx_control.py press 1      # start
    zx_control.py dump 0 65536 tmp/mem.bin

Pressing `3` during play aborts to the menu (the check at 0xAD21).
