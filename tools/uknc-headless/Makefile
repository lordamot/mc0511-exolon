# Builds the headless UKNC test runner against ukncbtl-qt's emubase core.
# Normally driven by tools/build_toolchain.py, which copies these sources
# into tmp/uknc-headless/ next to a tmp/ukncbtl-qt clone and runs make.
EMUBASE ?= ../ukncbtl-qt/emulator/emubase
CXX ?= g++
CXXFLAGS ?= -O2 -g -Wall -Wno-unused-variable -I. -I$(EMUBASE)
SRCS := main.cpp $(EMUBASE)/Board.cpp $(EMUBASE)/Processor.cpp \
        $(EMUBASE)/Memory.cpp $(EMUBASE)/Floppy.cpp $(EMUBASE)/Hard.cpp \
        $(EMUBASE)/Disasm.cpp $(EMUBASE)/SoundAY.cpp

SDL2RT ?= -l:libSDL2-2.0.so.0

.DEFAULT_GOAL := all
all: uknc-headless uknc-play

uknc-headless: $(SRCS) stdafx.h
	$(CXX) $(CXXFLAGS) -o $@ $(SRCS)

# The interactive player links against the host's SDL2 *runtime*
# (no dev package needed - see sdl2_min.h).
PLAY_SRCS := uknc-play.cpp $(EMUBASE)/Board.cpp $(EMUBASE)/Processor.cpp \
        $(EMUBASE)/Memory.cpp $(EMUBASE)/Floppy.cpp $(EMUBASE)/Hard.cpp \
        $(EMUBASE)/Disasm.cpp $(EMUBASE)/SoundAY.cpp

uknc-play: $(PLAY_SRCS) stdafx.h sdl2_min.h
	$(CXX) $(CXXFLAGS) -o $@ $(PLAY_SRCS) $(SDL2RT)

clean:
	rm -f uknc-headless uknc-play
