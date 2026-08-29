# Exolon UKNC port - design

Target: a faithful port of the ZX Spectrum game logic (see
`re-notes.md`) to the UKNC MC-0511, structured like
`../mc0511-brucelee-2`: boot sector + flat program on a raw `.dsk`,
MACRO-11 sources, a PPU program for video setup / keyboard / sound,
and every resource generated from editable text files.

## Memory map (CPU side, octal)

| Range | What |
|---|---|
| 0..777 | boot sector (src/boot.mac) |
| 1000..106xxx | program + data (code, tiles, lists, zones, sprites, strings) |
| 106xxx..116xxx | the PPU block: dead CPU RAM once it is loaded |
| 107000..136777 | back buffer: 192 lines x 32 cell words (planes 1+2) |
| 137000..144777 | cell buffer: 24 x 32 x {tile word, slot byte, class byte} |
| 145000..151546 | game variables, REVTAB / DUPTAB, entity and object lists |
| 160000 | stack top (RAM ends at 157777; the first push lands at 157776) |

The CPU-side copy of the PPU block (PP_START..PP_END, four kilobytes of
it) is dead once PP_MAIN_LOAD has pushed it into PPU RAM, so
src/exolon.list puts that block last, after every live byte, and the
back buffer starts where the live program ends and overlays it - which
is where the second sound engine found its room.  PROG_SIZE covers the
whole image (the loader reads it all in); BUF is the hand-set start of
the live program's dead tail, and tools/build_exolon.py fails the build
if the live program ever grows past it.

Planes are 64 KB each; the CPU address space *is* planes 1 and 2
interleaved (CPU byte 2N = plane1[N], 2N+1 = plane2[N]).  The visible
screen lives at plane offsets 0o100000+ and is reachable only through
`@#176640` (byte address) / `@#176642` (planes 1+2 as one word).
Plane 0 belongs to the PPU (`@#177010`/`@#177012`) and is left black:
rendering the zones with three inks plus black per 8-line row (compare
`tools/zone_render.py N out.png --uknc` with the same zone without the
flag) reproduces Exolon's screens almost exactly, so the extra plane is
not worth a per-zone PPU blit and the per-frame ones a moving sprite
would need.

## Video

- Whole screen 320 mode (mode word 27), 40 visible bytes per line,
  line stride 80 bytes, 288 lines.
- Game area = the ZX layout, 32 x 24 cells of 8 x 8 double-wide
  pixels: X offset 4 bytes, Y offset 48 lines.  Rows 0..21 are the
  zone, rows 22..23 the HUD - the same split as the original.
- Colour: planes 1+2 give pixel values 0/2/4/6, and every 8-line cell
  row carries its own 4-word palette element in the PPU line table
  (`ppu.mac NEW_TABLE`, `COMMAND_2` reloads all 24 from the CPU
  `ROWPALS` array).  So each row shows black plus **three inks chosen
  from the full 16-colour palette**, and each cell picks one of them
  independently - no attribute clash inside a row.
- The row palettes are computed **at zone load** from the cells the
  zone actually painted (`zone.mac ROW_PALETTE`): the three most
  used inks per row win, the rest snap to the nearest survivor.  That
  is the whole colour pipeline; no palette data is stored on disk.
- Tiles are 1bpp 8x8 glyphs exactly as on the ZX (8 bytes each; the
  bank holds 684, the font among them).  `CELL_DRAW` writes a cell into
  the back buffer by expanding the glyph into the two planes according
  to the cell's slot: 1 lights plane 1, 2 plane 2, 3 both.

## Processors

CPU: the game engine.  PPU (`src/ppu.mac`, loaded over channel K2 at
startup like brucelee): video line table + palettes, keyboard -> key
word in CPU RAM, the vsync flag, and the **sound engine** in its idle
loop.  The CPU asks for sounds through the `SND_REQ` / `SND_MODE`
mailbox words and picks the device with `SND_DEV`: 0 is the beeper
(speaker = bit 7 of PPU port 177716), 1 the AY sound module (three
AY-3-8910 on the PPU bus at 0177360/2/4 - word write = register
number, byte write = value; the game uses the first).  The beeper
engine is a timing loop and holds the PPU for as long as a sound
lasts; the AY engine runs a pass per 50 Hz tick and never blocks.
Menu option 5 switches between them live.

Music: Exolon's 48K release has beeper effects only, but the tape also
carries the 128K AY tune (three streams, see re-notes.md).
`tools/music_extract.py` decodes it and `tools/music_gen.py` renders it
for a three-voice beeper player on the PPU: each voice is a 16-bit
phase accumulator whose carry flips the speaker, so three square waves
are XORed onto one bit.  The same generator also emits `AY_PERIODS`,
the original's periods unchanged, which the AY player writes to the
chip a voice to a channel.  (UKNCBTL clocks its AY at about 1.41 MHz
rather than a real module's 1.77, so the tune sounds a major third
flat in the emulator - the periods are right, the emulator is not.)

Keyboard (PPU): arrows = left/right/jump/duck, space = fire, ФИКС or
numpad ВВОД = grenade, ENTER = menu select, АП2 = pause, СТОП = quit,
'1'..'5' = the title screen's options.  The key word has one bit per
key and only sixteen of them: '5' took bit 8 off the player-2 up arrow
this game has not got, the way '4' took bit 9 off the player-2 right.

## The game engine

Ported subsystem by subsystem from the RE:

- **zone loader** - runs the object list of the current zone through
  the display-list interpreter (`list.mac`), which fills the cell
  buffer (tile + ink + solid class) instead of a ZX screen; then the
  row palettes are computed and the whole area is expanded and
  blitted.  Live objects are appended to the object list with their
  bounding boxes, exactly as the original does.
- **player** - X in 2-pixel units, Y in pixels; walk 1 unit/frame, the
  22-frame jump arc table, crouch, the 10-frame walk cycle, facing,
  the power suit as a frame offset.  Floor and ceiling tests read the
  solid map.
- **bolts, grenades, missiles, sparks, energy balls and explosions** -
  one entity list (`shots.mac`), the kind picks the update rule through
  `EN_TAB` and four byte tables give each kind its collision box, its
  cell footprint and how much of a sprite frame it actually fills.  A
  bolt destroys any live object it hits, shoots down incoming fire and
  pops a force field's energy balls; a grenade climbs the original's
  arc, trails sparks and takes out the one live object whose box it
  goes off in.
- **enemies** - driven from the live object list: gun emplacements fire
  down their own row on the original's random trigger and play its
  eight-frame recoil, rocket banks launch when the player comes near,
  dishes and hoppers lob at him.  A force field fills its ring with
  drifting energy balls, the guns bolted to a wall spit along their own
  row, a mine keeps a homing missile coming in from the right, and a
  player who stays in one zone too long gets a rocket sent after him.
  Rocks, trees and mines kill on contact through their collision class.
- **HUD** - AMMO / GRENADES / POINTS / LIVES / ZONES, drawn from the
  same 8x8 font as the original.
- **flow** - death animation and respawn, lives, game over, the zone
  counter, and the title screen, which starts a game on "1" as the
  original's does and adds infinite lives on "2", a starting zone on
  "3" and the palette's colour order on "4".

## Resources (all editable text under src/res/)

| Resource | Source form | Generator |
|---|---|---|
| tiles | `res/tiles/tiles.txt` (`#` bitmaps) | `tools/tiles_gen.py` |
| scenery objects | `res/objects/objects.txt` (display lists) | `tools/objects_gen.py` |
| zones | `res/zones/zones.txt` (triples per zone) | `tools/zones_gen.py` |
| player sprites | `res/sprites/player.txt` | `tools/sprites_gen.py` |
| 16x16 sprites | `res/sprites/small.txt` | `tools/sprites_gen.py` |
| strings | `res/text/strings.txt` | `tools/text_gen.py` |
| music | `res/music/title.txt` | `tools/music_gen.py` |

The font is not a separate resource: the glyph bank holds it at tile
index = ASCII code, so text is drawn as tiles.  `res/objects/boxes.txt`
carries the live objects' bounding boxes, and `objects.txt` also names
the original menu's EXOLON logo with `alias LOGO`, which the title
screen replays.

`tools/extract_res.py` writes them all once from the tape; after that
they are the editable source of truth.

## Build

`make build`: generators -> `build/*.mac`, concatenate per
`src/exolon.list`, `bin/macro11 -yus -ysl 64`, `tools/obj2bin.py`,
`tools/dsk_build.py` -> `build/exolon.dsk`.  On the disk, LBA 0 is the
boot sector, LBA 1 an RT-11 home block whose volume identification
names the disk EXOLON (`tools/rt11_home.py`), and the rest of the
program follows from LBA 2, which is where the loader's parameter block
in `boot.mac` looks for it.  `make run` opens the SDL
player, `make shot` / `make demo` drive the headless emulator, and
`make verify` round-trips the resources and boots the image.

## Milestones

1. tooling, tape extraction, resources [DONE]
2. boot + PPU + zone rendering with per-row palettes [DONE]
3. player: walk / jump / duck / fire vs the collision map [DONE]
4. bolts, grenades, ammo, pickups [DONE]
5. enemies and hazards, death, lives, the power suit [DONE]
6. HUD, zone flow, all 125 zones [DONE]
7. beeper music + SFX in the PPU, and the same on an AY sound module
   with the title screen picking the device [DONE]
8. title screen with the original logo, pause, docs, verify [DONE]
9. the animation and behaviour passes: facing, the grenade's arc and
   smoke, the emplacement recoil, the teleport shower, force-field
   energy balls, mine missiles, the lingering-player rocket [DONE]
10. the wall emitters, the menu's two options, right-facing frames
    mirrored when they fly left, and the disk's name [DONE]
11. the double gun's two streams as separate targets, the power suit's
    twin guns, harmless explosions, and a generator worth the name
    [DONE]
12. the animation and enemy pass (see re-notes.md "second pass"): jet
    flames under the platforms, ships and pods; the booths' colour
    cycle; the land mines; the rising pumps; the vertical laser beam;
    the pylon arcs; object 39's free energy balls; the swooping flyers
    of seventy zones with the original's six paths and frame sets; the
    bolt as the original's 0xBD dash from two barrels six pixels
    apart; menu option 3 (start from a chosen zone); and the
    performance pass - the dirty-cell bitmap, frame-skip catch-up,
    and a kilobyte and a half of buffers moved out of the image [DONE]
13. class 16, the level gate (`src/gate.mac`): the end-of-level window
    with the LIVES and BRAVERY bonuses, the CONGRATULATIONS screen
    after zone 124, the EXOLON BONUS SCREEN with the fire-stopped
    pointer, the extra life / suit-off / refills, and the next level's
    entry position from the original's table at 0xAAE0; plus the
    entry-position pass - the pumps clipped at their ground line, the
    player lifted out of a mismatched entry floor after a zone load
    (`PL_SNAP`), and menu option 3 starting a later zone at the very
    left edge [DONE]
14. menu option 4: the palette's colour order, RGB or GRB, switched on
    the title screen and kept for the whole session [DONE]

Everything in the original is now ported.

## Notes from the implementation

- **Two things face the wrong way in the original.**  The player sheet
  has a single facing and the ZX plotter cannot mirror, so Vitorc walks
  left backwards; and the rocket that hunts a lingering player is drawn
  from a right-facing frame although it only ever flies left.  The
  missiles, on the other hand, face left already.  The port turns both
  of the wrong ones round through one 256-byte bit-reversal table:
  `SPRMIR` for the player, and `KINDMIR` in `shots.mac`, which records
  which way each kind's art faces and mirrors it when that disagrees
  with the direction it is travelling.

- **The generator matters more than the numbers it produces.**  Almost
  every timer in the original is "fire when a random byte clears a
  threshold", sampled once a frame per object, so what it needs is
  independence between consecutive calls.  A 16-bit LFSR stepped once
  per call does not have it - its bytes drift - and the wall guns fired
  in bursts that read as one long bullet.  `RANDOM` is a 16-bit LCG
  returning the high byte, which mixes the whole word every call.

- **A wall gun's two barrels are two targets.**  The bolt-against-shot
  test uses both boxes and gives slack only horizontally, where a bolt
  and its target can pass through each other inside a frame.  With none
  vertically, a standing shot reaches only the upper stream of a double
  gun and a crouched one only the lower - and the power suit becomes
  worth having, because it fires a heavier bolt from two barrels eight
  pixels apart and cuts down both at once.

- **Vitorc turns round, and the original's Vitorc does not.**  The ZX
  sheet has one facing and the plotter at 0x76DA has no mirror path, so
  walking left there is walking backwards.  The port draws the frame
  mirrored instead (`SPRMIR` in `gfx.mac`): each line's three source
  bytes swap ends and every byte's bits are reversed through a 256-byte
  table built at startup.  It is the one deliberate departure from the
  original's *look*, rather than from its rules.

- **Sprites are what the frame rate is made of.**  A moving sprite here
  costs several times what the ZX's XOR plotter did: the cells it
  covers have to be re-expanded out of the cell buffer, the sprite ORed
  into the back buffer, and the result blitted through the plane
  window.  What made a force field affordable was (a) `MARK_RECT`
  refusing duplicate rectangles and returning whether the mark was new,
  so `ENTS_ERASE` repaints a patch of background only once however many
  sprites sit on it, (b) per-kind sprite extents, since most of the
  frames this port added to the 16x16 sheet are eight pixels tall and
  eight wide, and (c) an inner loop that keeps the destination, the
  source and the line count in registers, recomputes the row's plane
  mask only when it crosses a cell row, and expands a source byte into
  a cell word through a lookup table.  Between them they roughly
  doubled the frame rate of a quiet zone.

  The one place the original's numbers did not survive is how many
  energy balls a force field emits: eight of them cost about a whole
  quiet frame, and since they all swirl inside the ring's two cells and
  overlap into one blob, `BALLS` is six, shared between the emitters of
  the handful of zones that have two.


- **The frame budget, and what happens beyond it.**  A busy zone
  (six energy balls, a flyer swarm, the pumps) costs more than a 20 ms
  frame.  Two answers ship together.  The dirty-cell bitmap: MARK_RECT
  sets bits (one per cell, two words a row) instead of appending to a
  rectangle list, and the blit pass pushes every dirty cell to the
  screen exactly once - overlapping sprites used to blit the same
  cells several times.  And frame-skip: when the vsync backlog shows
  the last frame overran, up to two update passes run with the sprite
  plotters gated off (`DRAWOFF`), then the third draws and blits - the
  game logic holds 50 Hz and the screen drops to half or a third rate
  instead of the whole game slowing down.  АР2 and СТОП edges seen by
  a catch-up pass's input read are latched (`PAUSEREQ`) and acted on
  once the frame is drawn.  `BENCHF` counts update passes and never
  resets; the headless emulator's `runrel` command runs until it has
  advanced N, which is what the gameplay tests count in.

- **Where the RAM ends.**  The UKNC CPU only has RAM below 0160000;
  0160000..0177777 is the I/O page in user mode.  Everything - program,
  back buffer, cell buffer, variables and stack - has to fit under
  that, which is why PROG_SIZE is 0115000 and the stack top 0160000
  (the first push predecrements to 0157776).
- **The palette nibble's colour bits have two orders in the wild.**
  A palette element stores an ink as bright + three colour bits, and
  machines and emulators disagree about whether those three read
  R/G/B or G/R/B; on the wrong one the sky is magenta and the grass
  red.  `INKNIB` and `INKNIBG` hold both ZX-ink-to-nibble maps (GRB is
  the identity, a ZX ink being bright/green/red/blue already) and
  `PALNIB` points at the one `PALORD` selects.  Everything that colours
  a row goes through `ROW_PALWORDS`, which now also records the row's
  three inks in `ROWINKS`, so `PAL_SETORD` can re-encode all 24
  palette elements from those and resend them with COMMAND_2 - which
  is what menu option 4 does, recolouring the title screen as the key
  is pressed.  The key itself is '4', scancode 013, and it took bit 9
  of the key word off the player-2 right arrow this game has not got.

- **The row palette is the whole colour pipeline.**  `ROW_ONE` weighs
  each ink in a row by the pixels its tiles light, keeps the three
  heaviest and snaps the rest to the nearest survivor (bitwise RGB
  distance, the brightness bit worth half a component).  Sprites use
  `WHITESL[row]`, the slot whose ink is nearest white; a playfield row
  whose third ink covers less than a quarter of its pixels hands that
  slot to white outright.  Every playfield row (8 and below) gives that
  slot up unconditionally: without it the player changes colour in the
  middle of a jump, when he rises into a row whose three inks happen to
  be heavy enough to keep the third.  Rows 0..7 are sky and only give
  it up when the third ink is a detail colour, so the planets keep
  their inks.
- **Collision follows the original's edges, not pixels.**  Walls are
  only tested when x is cell aligned, the floor only when y is, and the
  last few columns of a zone are always free (the original does the
  same at 0x80F3) - without that, edge scenery would trap the player
  where the zone should flip.
- **A class in the collision map is not automatically a wall.**  The
  original resolves this at zone load - `0x8E86` files every special
  class's cells under that class and leaves 0/1/3/13 in the map - so
  the port keeps the class in the cell and looks the solid/passable
  answer up in `BLOCKTAB` (player.mac), which is the same split.  The
  teleport and power-suit booths are found by scanning the finished map
  for classes 6 and 12 (`SPEC_SCAN` in zone.mac) and are operated with
  the up key, whose jump the booths' solid roofs cancel - exactly how
  the original gets away with sharing the key.
- **The laser is not a demolition tool, and neither is the grenade.**
  The original's bolt tests the sprite-occupancy map only, so
  emplacements and rock formations need a grenade; `OBJ_GRENONLY` in
  shots.mac holds that list.  The grenade in turn destroys exactly one
  thing - the live object whose bounding box holds the cell it went off
  in (0x93E2) - and leaves plain scenery alone.  Its reach is the arc,
  not a blast radius: thrown from under an emplacement it sails over,
  and from far enough back the dive brings it down on top of it.
- **Bolts and emplacement shots are single pixels** (`PIX_DRAW` in
  gfx.mac), which is as close as the UKNC gets to the original's
  two-pixel-resolution bullet pattern, and it is what makes ducking
  under a shot readable.
- **Destroying scenery replays its display list in erase mode**
  (`OBJ_ERASE`), so exactly the cells an object painted go blank.
  Clearing its bounding box instead would take the ground with it.
- **The sound register is not just a speaker.**  Writes to PPU port
  177716 must keep bit 15 set and bits 4-5 clear (they drive the CPU's
  ACLO/HALT/DCLO pins); bit 7 is the speaker and bits 8..12 gate fixed
  tone dividers, which this port leaves off.  A one-instruction pulse
  on bit 7 is inaudible - the level has to be toggled.
