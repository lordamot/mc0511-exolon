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

## Collision classes (0x8E86, table at 0x8EF4)

Opcode `E8 n` in a display list stores `n` into the solid map for
every cell it then paints, and the classes are how the game finds its
furniture.  The zone loader post-processes the finished map at
0x8E86: every cell whose class is >= 2 has its **position filed under
that class** and the map byte replaced, so after loading the map holds
only 0, 1, 3 and 13.  The table of 16 six-byte records at 0x8EF4 gives
class 2..17 its list, the stride of an entry and the byte to leave in
the map:

| class | list | stride | left in map | what it is |
|---|---|---|---|---|
| 2 | 0x8F89 | 2 | 0 | animated detail |
| 3 | 0x9022 | 3 | 3 | gun emplacement (solid) |
| 4 | 0x9135 | 2 | 0 | booth / gantry frame (walk-through) |
| 5 | 0x91B0 | 3 | 1 | animated solid |
| 6 | 0x9930 | 2 | 1 | **teleport pad** |
| 7 | 0x99F2 | 2 | 0 | **ammunition canister** |
| 8 | 0x99F5 | 2 | 0 | **grenade canister** |
| 9 | 0x9B4B | 2 | 0 | force-field beam |
| 10 | 0x9C70 | 3 | 1 | animated solid |
| 11 | 0x9DC1 | 2 | 0 | wall emitter (spits at the player) |
| 12 | 0x9F6E | 2 | 1 | **power-suit booth** |
| 13 | 0xA266 | 2 | 13 | mine |
| 14 | 0xA333 | 3 | 0 | wall emitter, second half |
| 15 | 0xA814 | 2 | 0 | animated detail |
| 16 | 0xAAEF | 2 | 0 | animated detail |
| 17 | 0xABCC | 2 | 1 | animated solid |

The "left in map" column is the solid/passable split: the frames of a
teleport booth and of the big gantries are class 4 and are meant to be
walked through, while the pad itself and the suit booth's roof stay
solid, which is what lets the same key both jump and operate them (see
below).

## Teleports (0x98BA) and the power suit (0x9F2D)

Both are worked by **pressing up while standing in them**, and both
have the same shape: an edge detector on the jump key (0x7B94, latched
in 0x9935 / 0x9F6D), then

    ld de,(pad) ; inc d ; call 0x9936   ; pad -> (x*4, (row+1)*8)
    ld a,(0x82F6) ; cp d ; ret nz       ; player's top line must match
    ld a,(0x82F5) ; sub e ; sub 9
    cp 0xEB ; ret c                     ; and x within [-12, +8] of it

The teleport (two pads, 0x9930 and 0x9932) then puts the player on the
other one at `x = pad*4 - 3`; the suit booth XORs 0x0C into the suit
frame offset at 0x9ED8.  Pressing up also starts a jump, but every
booth has a solid roof over the pad, so the ceiling test at 0x8179
cancels it before it moves the player - which is why the original can
run both checks *after* the player update and still see him standing
in the pad.  Object 17 is the teleport booth, object 29 the suit one.

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
(10..15), energy balls (16..19), the hunting rocket (36) and the rest
of the moving objects.

**The sheet has one facing.**  Every player frame draws Vitorc looking
right, and the plotter at 0x76DA has no mirror path - it picks one of
four pre-shift routines from `E & 3` and copies the shifted bytes
straight out.  So the original never turns him round: walking left, he
walks backwards.  (The port does turn him; see port-plan.md.)

There is a second, quite separate sprite bank at **0xED40**: 16x8
frames, each stored as four pre-shifted 16-byte copies (frame = 64
bytes), drawn by the XOR plotter at 0x92FB.  It holds the grenade
facing right and left (0, 1), three sizes of spark (3, 4, 5), a blank
(6), the force fields' energy ball (7) and the wall emitters' shot (8).
0x9E98 counts how many of these the frame has drawn and 0x9E85 pads the
count out to sixteen with the blank, so the frame takes the same time
however much is on screen; 0x9EAE/0x9E99 do the same for the 16x16
plotter, to six.

**One frame is drawn backwards.**  The missiles (10, 11) face left,
which is the way they always fly, but the rocket that hunts a lingering
player (36) faces right and flies left all the same.  The port mirrors
that one; the missiles it leaves alone.

## Bullets

List of 3-byte records {E, D, step} at 0x845F, updated at 0x83DD and
spawned at 0x8391.  The update tests the **sprite-occupancy map**
(0x9362 / 0x9382 through 0x80C1) and nothing else: a bolt kills the
moving enemies and the shots in the air, and it never touches scenery.
Gun emplacements and the rock formations that block a zone's exit are
the grenade's job.  The muzzle offset is +14 px in Y standing (+19
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

## The grenade (0x9208 spawn, 0x925F update, 0x93E2 blast)

One at a time - 0x925A is both the "in flight" flag and the arc index -
and only when the player is left of x = 0x76.  It leaves his shoulder,
not his hip: x = player x + 4, y = player y (+6 crouching), and the
facing (0x82FA) is both the x step, one unit an update, and the frame
(0 right, 1 left) in the 16x8 bank.

The arc is a table at 0x92DA read with the counter running 32 -> 1:

    -4 -4 -2 -2 -2 -1 -1 -1 -1  0 x22  +1

18 pixels up over nine steps, twenty-two level, and then +1 for ever -
the counter sticks at 1, so a grenade that hits nothing keeps sinking
until the ground stops it.  The main loop calls the update once a
frame while the counter is >= 0x13 and three times a frame below that
(the extra calls at 0x7604 and 0x761B), which is what makes the throw
start as a lob and finish as a dart.  While the counter is >= 0x13 it
also drops a spark four units behind itself every step (0x92C9), and
that trail is the whole of its animation.

It goes off at either edge of the zone, on the solid map ahead of it
(0x9362 / 0x9382), on the floor below it (0x93A2, skipped on the
arc's -1 steps) or below y = 0xA8.  0x93E2 then converts its position
to a cell and walks the live object list at 0x9437 for a box that
contains it: the first match is erased by replaying its display list
with the plotter vector switched to the "clear" one (0x99F8 with A=3),
flagged dead, and scored.  **Nothing else happens** - a grenade does
not open holes in plain scenery.  What it is for is the objects a
laser bolt cannot touch: the gun emplacements and the rock formations
that block a zone's exit.

## Sparks (0x981D spawn, 0x9835 animate)

Twenty 3-byte slots at 0x9870: {x, y, counter}.  A spark starts with
counter 10 and each frame draws the frame [0x9864 + counter] of the
16x8 bank after erasing [0x9865 + counter], which was last frame's -
the XOR plotter makes erase and draw the same operation.  The sequence
is 3, 4, 5, 5, 3, 5, 4, 5, 5, blank, so it twinkles rather than fades.
Nothing collides with a spark.

## Gun emplacements (class 3, list 0x9022, handler 0x8F95)

A 3-byte record per emplacement, {col, row, state}, sitting on the
object's own top-left cell.  It is neither aimed nor timed: in state 1
it draws a random byte every frame and fires when the byte is >= 0xFA,
about one frame in forty, and the shot always goes **left**, the side
the player comes from (0x9071 spawns it at y = row*8+3, x = col*4 with
step -1; 0x90A2 flies it, twice a frame).

Firing sets the state to 9, and states 9 down to 2 are the recoil: each
frame XORs out the tile pair the previous state used and XORs in the
pair for this one, over the emplacement's two anchor cells, from the
table at 0x9018 (tile 0x10 at rest, then 0x1E, 0x1C, 0x1A, 0x18, 0x16,
0x14, 0x12 and back to 0x10) with the tile base at 0xDDD8.  State 0
means the emplacement has been destroyed, which 0x8FB5 notices by
finding something other than 3 left in the solid map.

## The teleport's spark shower (0x9ED9 spawn, 0x9EEE animate)

Four 3-byte emitters at 0x9F13.  The teleport (0x98BA) starts one on
the pad it leaves and one on the pad it lands on, each with counter 20;
every frame each surviving emitter throws one spark at a random offset
inside four pixels by sixteen above its pad.  The warp itself is
instant - the shower is what reads as the travelling time.

## Force fields and their energy balls (0x9B07, 0x9A23)

Object 21's display list writes class 9 into one cell inside its ring
(and 0 into the rest of the hollow, 1 into the ring itself), so the
zone loader's class scan files that cell in the list at 0x9B4B and
leaves the map passable there.  0x9B07 then gives every entry **eight**
balls, all at the same point - x = col*4 + 2, y = row*8 + 3 - each with
a random step of +1 or -1, in the 24 four-byte slots at 0x9A99.

0x9A23 moves them: the step reverses at either edge of the zone, on
anything solid ahead (0x9362 / 0x9382) or on a random byte >= 0xDC,
about one frame in seven, and y wanders a pixel up or down each frame
unless 0x93A2 / 0x93C2 says the cell that way is solid.  The ring's own
cells are solid, so they swirl inside it.  They are drawn as frame 7 of
the 16x8 bank; 0x9B52 lets a laser bolt pop one for points and 0x9BB4
kills the player who touches one.

## Wall emitters (class 11, list 0x9DC1, fired at 0x9D7F)

Objects 26 and 45 - the guns bolted to a wall, one of them a stacked
pair - write class 11 on their muzzle cells and class 14 on the barrel
beside them, and the class scan leaves the map passable at both.  Each
class-11 cell is an independent gun: every frame it draws a random byte
and fires when the byte is >= 0xF7, about one frame in thirty, and only
while the player is still more than 0x1E units to its left.  The shot
goes into the ten 3-byte slots at 0x9E18 as {x = col*4 - 2, y = row*8,
step = -2}, is flown left by 0x9DD6 until it runs off the edge, kills
the player on a 4-by-8 box (0x9E64) and can be shot out of the air by
a laser bolt (0x9E37), which scores.  It is drawn as frame 8 of the
16x8 bank.

Class 14, the barrel cells, only knock themselves out when the player
walks into them (0xA30B) - no damage either way.

## Mines (class 13, 0xA23A launch, 0xA26B fly)

Object 31 writes class 13 on its anchor cell, and the class stays 13 in
the map.  A zone has one mine's worth of state - the cell at 0xA266,
the missile at 0xA268, the flag at 0xA26A - and 0xA23A relaunches as
soon as the last missile is gone, as long as that cell still reads 13:
x = 0x78, y = a random 0x20..0x9F.  0xA26B flies it left one unit a
frame down to x = 0x46 and two after that (16x16 frames 10 and 11),
moving one pixel a frame towards the player's own y, and kills him on a
16-by-8 box.  Shooting the mine out is the only way to stop them; the
missiles themselves cannot be shot down.

## The rocket for a player who lingers (0xAC59, 0xAC7D)

0xAC7B counts frames since the zone was loaded (0x7682), and is reset
by the zone loader (0x8497) and by death (0x9CBE).  At **700** frames
0xAC59 arms a rocket at x = 0x78 and whatever y the player is at, and
0xAC7D flies it left two units a frame as 16x16 frame 36, dropping a
spark at (x+6, y+4) on about half the frames once x is below 0x6F.  It
kills on a 16-by-8 box and disarms itself at x = 0, so there is exactly
one per visit to a zone - staying put simply gets you killed.

## Box tests against the player (0x9BD6)

BC carries the box: C = its width in x units, B = its height in
pixels.  It hits when the player's x is within [-12, C-1] of the
entity's and his y within [-32, B-1] of it, the 12 and the 32 being
the player sprite's own size; crouching takes a different y branch.
The numbers the callers pass are 0x0804 for an energy ball or a wall
emitter's shot (4 units by 8 pixels) and 0x1008 for a mine's missile
and the hunting rocket (16 by 8).

Crouching (0x9C00) takes the player's top down by six pixels and leaves
his feet where they are - 26 lines instead of 32 - and that six pixels
is the whole of what ducking buys: a gun emplacement's shot leaves the
muzzle at `row*8 + 3`, three pixels into the cell above the one the
player's head fills when he stands on the floor below it.

## Randomness

`0xAD36` returns the Z80's refresh register, which is uncorrelated
enough for what the game asks of it: almost every timer in Exolon is
"fire when a random byte is over a threshold", read once per frame per
object.  Anything that stands in for it has to be uncorrelated *between
consecutive calls*, not merely uniform over time - a generator whose
successive bytes drift slowly turns those thresholds into bursts, and
the wall guns lay down a solid line of shots instead of the odd one.

## The animated scenery classes (recovered in the second pass)

The class handlers the first pass skipped, all driven from the main
loop once a frame.  The `EB n` display-list opcode files the cursor
cell under class n *without* touching the solid map, which is how the
runtime-only objects (22, 39, 42, 51) get their anchors; the port
carries it as the `anim n` statement and opcode 0353.

| class | handler | what it is |
|---|---|---|
| 2 | 0x8F5A | jet flame: two tiles below the anchor cycle through three pairs (tiles 0x15..0x1A, base 0xDAB8) in a fresh random bright ink every frame; one three-step counter is shared by every flame.  Objects 1 (platform, two jets), 2 (spaceship, two jets) and 28 (pod) |
| 4 | 0x9118 | booth / gantry frame: the attribute of every cell rewritten from the frame counter - the teleport booths' shimmer |
| 5 | 0x9152 / 0x9186 | land mine (object 12): armed it sits still (records {col,row,1}); when the player's feet are on its top line and his x within [-7,+2] of it, it disarms, erases, and kills through 0x9CAA - which returns while the power suit is on.  A blown mine's two cells then flicker forever through the burning pair (tiles 0x1D..0x20) |
| 10 | 0x9C15 / 0x9C8B | the rising pump (object 22, `EB 10`): a per-pump counter rests below 0x65, then four frames up, eleven held, four down, reroll to 0x14+rand&0x3F.  Drawn from *player-bank* frame 24 (24x32); while it cycles, a 12-unit by 32-line box kills through 0x9CAA (suit walks over) |
| 15 | 0xA7D6 | pylon arc (objects 42, 51, `EB 15`): two 16x16 frames side by side, a random frame of 28..31 and its neighbour, redrawn every frame in a random ink.  Scenery, not a hazard |
| 16 | 0xA817 | level-gate anchor (object 42, `EB 16`, zones 24/49/74/99/124): when the player's x reaches it, the inter-level bonus screen at 0xA8DB runs (pointer minigame, extra life, suit off, refills).  NOT PORTED YET |
| 17 | 0xAB94 / 0xABCF / 0xAC04 | the vertical laser beam (object 1's centre cell): drawn from under the platform down to the first solid cell (tile 0x25), recoloured from the frame counter every frame, kills the player whose x+12 equals its column (no suit protection), and falls after 0x19=25 laser bolts pass the cell column just left of it, which scores |

Object 39 (`EB 9`, 28 placements) is the free-ball variant of the
force field: its hook cell goes into the same class-9 list, so eight
(here: the shared budget) energy balls drift loose between the pylons.

## The swooping flyers (0xA553 spawn, 0xA360 fly, 0xA645 config)

Seventy zones send flyers in.  Per-zone config at 0xA677: {zone, path
ptr, 16x16 frame base, spawn cooldown}, self-modified into the code at
zone load.  Six slots of ten bytes at 0xA508: {x, y, active, path ptr
x2, path start x2, repeat, phase, ?}.

Spawn (0xA553): only while the player is left of x=0x54, a free slot
exists, and a random byte comes up >= 0xC8; x=0x78, y = player's +
rand&0x0F (or -10 when rand >= 0xAF); then the cooldown holds the next
one off.  Fly (0xA360): the path byte code - {dx,dy} signed pairs,
0xC4 n = repeat the next pair n times in all, 0xC3 = back to the
start; dies at x >= 0x80 or y >= 0xB0.  Drawn as frame base +
(phase & 3): bases 1, 16 (the spheres), 20, 24, 37, 41.  The six paths
at 0xA406..0xA507: a looping sine swoop, the same swoop accelerating
away, a loop-the-loop, a straight dart, a dip-and-hold, a zigzag.

A laser bolt kills one (tested from the bullet update, 0x83E3 ->
0xA5CA), which explodes and scores; touching one is fatal (0xA5F4,
a 4-by-8 box about its middle, via 0x9CAF - the suit does not help).

## The bullet, drawn

0x82FC draws a bullet as the 16-bit pattern 0x00BD shifted by
(~E & 3)+1 double-pixels across two screen bytes and XORed on: the
dash X.XXXX.X at two-pixel resolution.  The suit's second bullet
leaves six pixels below the first (0x8384: `add a,6`).  The update
0x83DD runs five times per game loop at one unit a step - that is
both the speed (10 px/frame) and why it cannot step over a thin wall.
