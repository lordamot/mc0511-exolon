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
| 1000..107777 | program + data (code, tiles, lists, zones, sprites) |
| 110000..137777 | back buffer: 192 lines x 32 cell words (planes 1+2) |
| 140000..145777 | cell buffer: 24 x 32 x {tile word, slot byte, class byte} |
| 146000..152000 | game variables, entity and object lists |
| 157000 | stack top (RAM ends at 157777; above that is the I/O page) |

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
  bank holds 672, the font among them).  `CELL_DRAW` writes a cell into
  the back buffer by expanding the glyph into the two planes according
  to the cell's slot: 1 lights plane 1, 2 plane 2, 3 both.

## Processors

CPU: the game engine.  PPU (`src/ppu.mac`, loaded over channel K2 at
startup like brucelee): video line table + palettes, keyboard -> key
word in CPU RAM, the vsync flag, and the **beeper sound engine** in
its idle loop (speaker = bit 7 of PPU port 177716).  The CPU asks for
sounds through the `SND_REQ` / `SND_MODE` mailbox words.

Music: Exolon's 48K release has beeper effects only, but the tape also
carries the 128K AY tune (three streams, see re-notes.md).
`tools/music_extract.py` decodes it and `tools/music_gen.py` renders it
for a three-voice beeper player on the PPU: each voice is a 16-bit
phase accumulator whose carry flips the speaker, so three square waves
are XORed onto one bit.

Keyboard (PPU): arrows = left/right/jump/duck, ФИКС or space = fire,
numpad ВВОД = grenade, ENTER = menu select, АП2 = pause, СТОП = quit.

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
  drifting energy balls, a mine keeps a homing missile coming in from
  the right, and a player who stays in one zone too long gets a rocket
  sent after him.  Rocks, trees and mines kill on contact through their
  collision class.
- **HUD** - AMMO / GRENADES / POINTS / LIVES / ZONES, drawn from the
  same 8x8 font as the original.
- **flow** - death animation and respawn, lives, game over, the zone
  counter, the menu and the title screen.

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
`tools/dsk_build.py` -> `build/exolon.dsk`.  `make run` opens the SDL
player, `make shot` / `make demo` drive the headless emulator, and
`make verify` round-trips the resources and boots the image.

## Milestones

1. tooling, tape extraction, resources [DONE]
2. boot + PPU + zone rendering with per-row palettes [DONE]
3. player: walk / jump / duck / fire vs the collision map [DONE]
4. bolts, grenades, ammo, pickups [DONE]
5. enemies and hazards, death, lives, the power suit [DONE]
6. HUD, zone flow, all 125 zones [DONE]
7. beeper music + SFX in the PPU [DONE]
8. title screen with the original logo, pause, docs, verify [DONE]
9. the animation and behaviour passes: facing, the grenade's arc and
   smoke, the emplacement recoil, the teleport shower, force-field
   energy balls, mine missiles, the lingering-player rocket [DONE]

## Notes from the implementation

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


- **Where the RAM ends.**  The UKNC CPU only has RAM below 0160000;
  0160000..0177777 is the I/O page in user mode.  Everything - program,
  back buffer, cell buffer, variables and stack - has to fit under
  that, which is why PROG_SIZE is 0110000 and the stack top 0157000.
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
