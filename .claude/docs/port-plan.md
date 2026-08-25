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
- **bolts, grenades, missiles and explosions** - one entity list, the
  kind picks the update rule.  A bolt destroys any live object it hits
  and shoots down incoming missiles; a grenade flies in an arc and
  blows a hole in solid scenery.
- **enemies** - driven from the live object list: gun emplacements and
  small guns fire along the player's row, rocket banks launch when he
  comes near, dishes and hoppers lob at him.  Rocks, trees, mines and
  force fields kill on contact through their collision class.
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

## Notes from the implementation

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
  slot to white outright.  Rows 0..7 are sky and are left alone, so the
  planets keep their inks.
- **Collision follows the original's edges, not pixels.**  Walls are
  only tested when x is cell aligned, the floor only when y is, and the
  last few columns of a zone are always free (the original does the
  same at 0x80F3) - without that, edge scenery would trap the player
  where the zone should flip.
- **Destroying scenery replays its display list in erase mode**
  (`OBJ_ERASE`), so exactly the cells an object painted go blank.
  Clearing its bounding box instead would take the ground with it.
- **The sound register is not just a speaker.**  Writes to PPU port
  177716 must keep bit 15 set and bits 4-5 clear (they drive the CPU's
  ACLO/HALT/DCLO pins); bit 7 is the speaker and bits 8..12 gate fixed
  tone dividers, which this port leaves off.  A one-instruction pulse
  on bit 7 is inaudible - the level has to be toggled.
