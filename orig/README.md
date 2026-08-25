Unpacked originals, all derived from `EXOLON.TAP`:

- `tap/*.bin` - the raw tape blocks (`tools/tap_extract.py save`)
- `game48k.bin` - the 48K memory image the game runs in, block 7 laid
  down at 0x6D60 (`tools/exolon_re.py:load_image()`); this is what the
  disassembly and extraction addresses in `.claude/docs/re-notes.md`
  refer to
