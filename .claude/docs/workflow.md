# Working on this port

Recipes for the two emulators, which is how everything here was
developed and checked.  Both drivers are Python and live in `tools/`.

## The UKNC side (the port)

`tools/uknc_control.py` wraps `bin/ukncbtl/uknc-headless`.  Its
`script` sub-command runs a raw emulator script, and that is the useful
one - the emulator understands:

    run N                 run N frames
    runrel ADDR N [MAX]   run until the CPU word at octal ADDR has
                          advanced by N (decimal) - with BENCHF from
                          build/exolon.lst this is "run the game
                          exactly N frames", however slow the zone
    press CODE [HOLD]     press and release an octal UKNC scancode
    keydown CODE          hold a key
    keyup CODE            release it
    screenshot FILE.bmp   640x288 screenshot
    peekcpu OCTAL         read a CPU word
    pokecpu OCTAL B B ..  write CPU bytes
    dumpcpu OCTAL LEN F   dump CPU memory to a file
    regs                  CPU and PPU registers
    wavstart / wavstop F  record the speaker to a .wav
    quit

Scancodes: 133 right, 116 left, 154 up, 134 down, 107 ФИКС (fire),
166 numpad ВВОД (grenade), 153 ENTER, 006 АП2, 004 СТОП, 030 the
firmware menu's "1".

A session always starts with the firmware loader:

    run 900
    press 030
    run 30
    press 153
    run 320        ; the disk load and the title screen
    press 153 5    ; ENTER starts a game

Zone loading takes about eight frames (a full expand plus a full blit),
so give it `run 40` before screenshotting after forcing a zone.

Useful pokes - the addresses come out of `build/exolon.lst` (they move
with every gamevars change, so always look them up):

    pokecpu <ZONE> 36 0      ; ZONE = 30
    pokecpu <ZONELOAD> 1 0   ; reload it now
    pokecpu <CHEAT> 2 0      ; 2 = invulnerable (testing aid; the menu
                             ; only ever sets 1 = infinite lives)

The game runs update passes without drawing when it falls behind
(frame-skip), so a memory dump taken at a tick boundary can catch the
back buffer between passes.  A test that compares pixels should press
АР2 first - pause always freezes a fully drawn frame - and dump then.

Two things that are easy to get wrong:

- **The screen and the back buffer are different pictures.**  When
  something looks wrong, `dumpcpu 0110000 12288` gives the back buffer
  and `dumpcpu 0140000 3072` the cell buffer; rendering those in Python
  says immediately whether the bug is in the model, the expansion or
  the blit.
- **The captured `.wav` is sampled at 22 kHz.**  A one-instruction
  pulse on the speaker bit simply is not there; count zero crossings to
  measure a tone, and calibrate pitch with a one-note tune rather than
  by reading the music data.

## The ZX Spectrum side (the original)

`tools/zx_control.py` drives ZEsarUX over its remote protocol:

    python3 tools/zx_control.py launch --tap EXOLON.TAP --machine 48k \
        --romfile /usr/share/spectrum-roms/48.rom
    python3 tools/zx_control.py press J SYM_SHIFT+P SYM_SHIFT+P ENTER
    # wait ~25 s for the tape, then:
    python3 tools/zx_control.py press 5     # Kempston
    python3 tools/zx_control.py press 1     # start
    python3 tools/zx_control.py dump 0 65536 tmp/mem.bin
    python3 tools/zx_control.py screenshot tmp/x.bmp
    python3 tools/zx_control.py stop

Pressing `3` during play aborts back to the menu.  For static work the
tape image alone is enough: `exolon_re.load_image()` rebuilds the 48K
image without an emulator at all.

## Reading the original

    python3 tools/tap_extract.py list EXOLON.TAP
    python3 tools/z80_trace.py tmp/img.bin --org 0 --root 0x6d60
    python3 tools/z80dis.py tmp/img.bin 0 0x8485 0x8530
    python3 tools/zx_view.py bitmap tmp/img.bin 0 0xef80 out.png \
        --width 3 --height 32

`tools/exolon_re.py` is the library the extractors use: it holds the
tape layout, the original's display-list interpreter and the zone
tables, and `render_zone()` paints any zone exactly as the game does.
`tools/zone_render.py` does the same from the editable resources, so
comparing the two is the regression test behind `make verify`.
