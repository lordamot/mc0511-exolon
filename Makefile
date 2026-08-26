BUILD_DIR := build
GAME_DSK := $(BUILD_DIR)/exolon.dsk

.PHONY: build run shot demo verify extract toolchain clean

# sources -> bootable raw .dsk: resource generators (tiles, display
# lists, zones, sprites, strings, music), MACRO-11 modules concatenated
# per src/exolon.list, assembled with bin/macro11, linked flat, disk
# laid out (program at LBA 0)
build:
	python3 tools/build_exolon.py $(GAME_DSK)

# build, then open a playable emulator window (SDL2, UKNCBTL core).
# It boots the firmware loader by itself; arrows move and jump,
# ФИКС/space fires, numpad ВВОД throws a grenade, ENTER starts.
run: build
	bin/ukncbtl/uknc-play --rom bin/ukncbtl/uknc_rom.bin --disk $(GAME_DSK)

# headless proof-of-life: boot to the title screen, screenshot it
shot: build
	python3 tools/uknc_control.py boot --disk $(GAME_DSK) --wait 400 \
	    --shot tmp/run-title.png

# start a game (the title screen starts on "1") and screenshot zone 0
demo: build
	python3 tools/uknc_control.py play --disk $(GAME_DSK) 1 \
	    --every 60 --wait 260 --shot tmp/run-demo.png

# resource round-trips, generator determinism, and a boot-to-gameplay
# smoke test in the headless emulator
verify: build
	python3 tools/verify_build.py

# re-extract every resource from EXOLON.TAP (destructive: it overwrites
# src/res, including the two sprite frames added by hand)
extract:
	python3 tools/extract_res.py --force
	python3 tools/music_extract.py --force

# rebuild macro11 and the emulators from source into bin/
toolchain:
	python3 tools/build_toolchain.py

clean:
	rm -rf $(BUILD_DIR)
