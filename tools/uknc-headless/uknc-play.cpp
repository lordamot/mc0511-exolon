/*  uknc-play -- interactive UKNC (Elektronika MS 0511) emulator window
    built on the emubase core of UKNCBTL (https://github.com/nzeemin/ukncbtl-qt,
    LGPL v3) and the host's SDL2 runtime (see sdl2_min.h for why the ABI
    is declared by hand).  This is `make run`: boot the game disk and play.

    Usage:
        uknc-play --rom uknc_rom.bin --disk build/exolon.dsk [--no-autoboot]

    By default the firmware loader menu is driven automatically
    ("1 - диск" + ВВОД), landing straight on the title screen.

    Keys:
        arrows           move / jump / crouch
        Space or LCtrl   ФИКС      (fire)
        KP Enter, RCtrl  доп. ВВОД (throw a grenade)
        Enter            ВВОД      (menu select)
        Tab              АР2       (pause)
        Esc              СТОП
        1..0             UKNC digit row ("1" starts a game)
        close window     quit the emulator
*/

#include "stdafx.h"
#include "Emubase.h"
#include "sdl2_min.h"

#include <vector>

static CMotherboard *g_pBoard = nullptr;

// --- speaker output -------------------------------------------------
// emubase calls this 882 times per SystemFrame (SAMPLERATE 22050 / 25);
// the samples collect here and the main loop queues them on the SDL
// audio device once a frame.
static std::vector<int16_t> g_audioBuf;
static void CALLBACK AudioCallback(unsigned short L, unsigned short /*R*/)
{
    g_audioBuf.push_back((int16_t)((int)L - 16384));
}

// YRGB -> RGB32 palette (ScreenView_StandardRGBColors from UKNCBTL).
static const uint32_t g_colors[16 * 8] =
{
    0xFF000000, 0xFF000080, 0xFF008000, 0xFF008080, 0xFF800000, 0xFF800080, 0xFF808000, 0xFF808080,
    0xFF000000, 0xFF0000FF, 0xFF00FF00, 0xFF00FFFF, 0xFFFF0000, 0xFFFF00FF, 0xFFFFFF00, 0xFFFFFFFF,
    0xFF000000, 0xFF000060, 0xFF008000, 0xFF008060, 0xFF800000, 0xFF800060, 0xFF808000, 0xFF808060,
    0xFF000000, 0xFF0000DF, 0xFF00FF00, 0xFF00FFDF, 0xFFFF0000, 0xFFFF00DF, 0xFFFFFF00, 0xFFFFFFDF,
    0xFF000000, 0xFF000080, 0xFF006000, 0xFF006080, 0xFF800000, 0xFF800080, 0xFF806000, 0xFF806080,
    0xFF000000, 0xFF0000FF, 0xFF00DF00, 0xFF00DFFF, 0xFFFF0000, 0xFFFF00FF, 0xFFFFDF00, 0xFFFFDFFF,
    0xFF000000, 0xFF000060, 0xFF006000, 0xFF006060, 0xFF800000, 0xFF800060, 0xFF806000, 0xFF806060,
    0xFF000000, 0xFF0000DF, 0xFF00DF00, 0xFF00DFDF, 0xFFFF0000, 0xFFFF00DF, 0xFFFFDF00, 0xFFFFDFDF,
    0xFF000000, 0xFF000080, 0xFF008000, 0xFF008080, 0xFF600000, 0xFF600080, 0xFF608000, 0xFF608080,
    0xFF000000, 0xFF0000FF, 0xFF00FF00, 0xFF00FFFF, 0xFFDF0000, 0xFFDF00FF, 0xFFDFFF00, 0xFFDFFFFF,
    0xFF000000, 0xFF000060, 0xFF008000, 0xFF008060, 0xFF600000, 0xFF600060, 0xFF608000, 0xFF608060,
    0xFF000000, 0xFF0000DF, 0xFF00FF00, 0xFF00FFDF, 0xFFDF0000, 0xFFDF00DF, 0xFFDFFF00, 0xFFDFFFDF,
    0xFF000000, 0xFF000080, 0xFF006000, 0xFF006080, 0xFF600000, 0xFF600080, 0xFF606000, 0xFF606080,
    0xFF000000, 0xFF0000FF, 0xFF00DF00, 0xFF00DFFF, 0xFFDF0000, 0xFFDF00FF, 0xFFDFDF00, 0xFFDFDFFF,
    0xFF000000, 0xFF000060, 0xFF006000, 0xFF006060, 0xFF600000, 0xFF600060, 0xFF606000, 0xFF606060,
    0xFF000000, 0xFF0000DF, 0xFF00DF00, 0xFF00DFDF, 0xFFDF0000, 0xFFDF00DF, 0xFFDFDF00, 0xFFDFDFDF,
};

// Render the current screen into a 640x288 RGB32 buffer -- the same
// routine as in main.cpp (Emulator_PrepareScreenRGB32 from UKNCBTL).
static void PrepareScreenRGB32(uint32_t *pImageBits, const uint32_t *colors)
{
    uint8_t  cursorYRGB = 0;
    bool     okCursorType = false;
    uint8_t  cursorPos = 128;
    bool     cursorOn = false;
    uint8_t  cursorAddress = 0;
    uint16_t address = 0000270;
    bool     okTagSize = false;
    bool     okTagType = false;
    int      scale = 1;
    uint32_t palette = 0;
    uint32_t palettecurrent[8];
    for (int i = 0; i < 8; i++)
        palettecurrent[i] = 0xFF000000;
    uint8_t pbpgpr = 0;

    for (int yy = 0; yy < 307; yy++)
    {
        if (okTagSize)
        {
            uint16_t tag1 = g_pBoard->GetRAMWord(0, address);
            address += 2;
            uint16_t tag2 = g_pBoard->GetRAMWord(0, address);
            address += 2;

            if (okTagType)
                palette = ((uint32_t)tag1) | ((uint32_t)tag2 << 16);
            else
            {
                scale = (tag2 >> 4) & 3;
                pbpgpr = (uint8_t)((7 - (tag2 & 7)) << 4);
                cursorYRGB = (uint8_t)(tag1 & 15);
                okCursorType = ((tag1 & 16) != 0);
                cursorPos = (uint8_t)(((tag1 >> 8) >> scale) & 0x7f);
                cursorAddress = (uint8_t)((tag1 >> 5) & 7);
                scale = 1 << scale;
            }
            for (uint8_t c = 0; c < 8; c++)
            {
                uint8_t valueYRGB = (uint8_t)(palette >> (c << 2)) & 15;
                palettecurrent[c] = colors[pbpgpr | valueYRGB];
            }
        }

        uint16_t addressBits = g_pBoard->GetRAMWord(0, address);
        address += 2;

        uint16_t tagB = g_pBoard->GetRAMWord(0, address);
        okTagSize = (tagB & 2) != 0;
        if (okTagSize)
        {
            address = tagB & ~7;
            okTagType = (tagB & 4) != 0;
        }
        else
            address = tagB & ~3;
        if ((tagB & 1) != 0)
            cursorOn = !cursorOn;

        if (yy < 19)
            continue;

        int xr = 640;
        int y = yy - 19;
        uint32_t *pBits = pImageBits + y * 640;
        int pos = 0;
        for (;;)
        {
            uint8_t src0 = g_pBoard->GetRAMByte(0, addressBits);
            uint8_t src1 = g_pBoard->GetRAMByte(1, addressBits);
            uint8_t src2 = g_pBoard->GetRAMByte(2, addressBits);
            int bit = 0;
            for (;;)
            {
                uint32_t valueRGB;
                if (cursorOn && (pos == cursorPos) &&
                    (!okCursorType || (okCursorType && bit == cursorAddress)))
                    valueRGB = colors[cursorYRGB];
                else
                {
                    uint8_t value012 = (src0 & 1) | ((src1 & 1) << 1) | ((src2 & 1) << 2);
                    valueRGB = palettecurrent[value012];
                }

                for (int s = 0; s < scale && xr > 0; s++)
                {
                    *pBits++ = valueRGB;
                    xr--;
                }

                if (bit == 7)
                    break;
                bit++;
                src0 >>= 1;
                src1 >>= 1;
                src2 >>= 1;
            }
            if (xr <= 0)
                break;
            addressBits++;
            pos++;
        }
    }
}

// host SDL scancode -> UKNC keyboard matrix code
static int MapKey(int32_t sc)
{
    switch (sc)
    {
    case SC_UP:       return 0154;
    case SC_DOWN:     return 0134;
    case SC_LEFT:     return 0116;
    case SC_RIGHT:    return 0133;
    case SC_RETURN:   return 0153;   // ВВОД
    case SC_SPACE:
    case SC_LCTRL:    return 0107;   // ФИКС - player 1 fire
    case SC_KP_ENTER:
    case SC_RCTRL:    return 0166;   // доп. ВВОД - player 2 fire
    case SC_TAB:      return 0006;   // АР2
    case SC_ESCAPE:   return 0004;   // СТОП
    }
    if (sc >= SC_1 && sc <= SC_0)    // digit row 1..9,0
    {
        static const int digits[10] =
            { 0030, 0031, 0032, 0013, 0034, 0035, 0016, 0017, 0177, 0176 };
        return digits[sc - SC_1];
    }
    return -1;
}

int main(int argc, char *argv[])
{
    const char *romPath = nullptr;
    const char *diskPath = nullptr;
    bool autoboot = true;

    for (int i = 1; i < argc; i++)
    {
        if (!strcmp(argv[i], "--rom") && i + 1 < argc)
            romPath = argv[++i];
        else if (!strcmp(argv[i], "--disk") && i + 1 < argc)
            diskPath = argv[++i];
        else if (!strcmp(argv[i], "--no-autoboot"))
            autoboot = false;
        else
        {
            fprintf(stderr, "unknown option: %s\n", argv[i]);
            return 1;
        }
    }
    if (!romPath)
    {
        fprintf(stderr, "--rom is required (uknc_rom.bin)\n");
        return 1;
    }

    uint8_t rom[32768];
    memset(rom, 0, sizeof(rom));
    FILE *f = fopen(romPath, "rb");
    if (!f)
    {
        fprintf(stderr, "cannot open ROM %s\n", romPath);
        return 1;
    }
    size_t n = fread(rom, 1, sizeof(rom), f);
    fclose(f);
    if (n < 16384)
    {
        fprintf(stderr, "ROM file too small (%zu bytes)\n", n);
        return 1;
    }

    CProcessor::Init();
    g_pBoard = new CMotherboard();
    g_pBoard->LoadROM(rom);
    g_pBoard->Reset();
    if (diskPath && !g_pBoard->AttachFloppyImage(0, diskPath))
    {
        fprintf(stderr, "cannot attach disk %s\n", diskPath);
        return 1;
    }

    if (SDL_Init(SDL_INIT_VIDEO) != 0)
    {
        fprintf(stderr, "SDL_Init failed: %s\n", SDL_GetError());
        return 1;
    }

    // the beeper: 22050 Hz mono S16, pushed with SDL_QueueAudio; if the
    // host has no usable audio the game still runs, just silent
    uint32_t audioDev = 0;
    if (SDL_InitSubSystem(SDL_INIT_AUDIO) == 0)
    {
        SDL_AudioSpec want;
        memset(&want, 0, sizeof(want));
        want.freq = 22050;
        want.format = AUDIO_S16LSB;
        want.channels = 1;
        want.samples = 1024;
        audioDev = SDL_OpenAudioDevice(nullptr, 0, &want, nullptr, 0);
        if (audioDev)
        {
            g_pBoard->SetSoundGenCallback(AudioCallback);
            SDL_PauseAudioDevice(audioDev, 0);
        }
    }
    if (!audioDev)
        fprintf(stderr, "no audio device, running silent: %s\n",
                SDL_GetError());
    SDL_Window *win = SDL_CreateWindow("Exolon  \xd0\xa3\xd0\x9a\xd0\x9d\xd0\xa6 \xd0\x9c\xd0\xa1-0511",
                                       (int)SDL_WINDOWPOS_CENTERED,
                                       (int)SDL_WINDOWPOS_CENTERED,
                                       1280, 960, SDL_WINDOW_RESIZABLE);
    if (!win)
    {
        fprintf(stderr, "SDL_CreateWindow failed: %s\n", SDL_GetError());
        return 1;
    }
    SDL_Renderer *ren = SDL_CreateRenderer(win, -1, 0);
    if (!ren)
    {
        fprintf(stderr, "SDL_CreateRenderer failed: %s\n", SDL_GetError());
        return 1;
    }
    SDL_RenderSetLogicalSize(ren, 640, 480);  // UKNC pixels on a 4:3 screen
    SDL_Texture *tex = SDL_CreateTexture(ren, SDL_PIXELFORMAT_ARGB8888,
                                         SDL_TEXTUREACCESS_STREAMING, 640, 288);
    if (!tex)
    {
        fprintf(stderr, "SDL_CreateTexture failed: %s\n", SDL_GetError());
        return 1;
    }

    std::vector<uint32_t> bits(640 * 288, 0);
    long frame = 0;
    bool running = true;
    uint32_t next = SDL_GetTicks();

    while (running)
    {
        SDL_Event ev;
        while (SDL_PollEvent(&ev))
        {
            if (ev.type == SDL_QUIT_EVENT)
                running = false;
            else if ((ev.type == SDL_KEYDOWN_EVENT || ev.type == SDL_KEYUP_EVENT)
                     && !ev.key.repeat)
            {
                int code = MapKey(ev.key.keysym.scancode);
                if (code >= 0)
                    g_pBoard->KeyboardEvent((uint8_t)code,
                                            ev.type == SDL_KEYDOWN_EVENT);
            }
        }

        // drive the firmware loader menu: "1 - диск" + ВВОД
        if (autoboot)
        {
            switch (frame)
            {
            case 900: g_pBoard->KeyboardEvent(0030, true); break;
            case 905: g_pBoard->KeyboardEvent(0030, false); break;
            case 935: g_pBoard->KeyboardEvent(0153, true); break;
            case 940: g_pBoard->KeyboardEvent(0153, false); break;
            }
        }

        g_pBoard->SystemFrame();   // 1/25 s of emulated time
        frame++;

        if (audioDev)
        {
            // keep at most ~4 frames (160 ms) queued so audio latency
            // cannot build up when a frame overruns its 40 ms slot
            if (SDL_GetQueuedAudioSize(audioDev) < 4 * 882 * 2)
                SDL_QueueAudio(audioDev, g_audioBuf.data(),
                               (uint32_t)(g_audioBuf.size() * 2));
            g_audioBuf.clear();
        }

        PrepareScreenRGB32(bits.data(), g_colors);
        SDL_UpdateTexture(tex, nullptr, bits.data(), 640 * 4);
        SDL_RenderClear(ren);
        SDL_RenderCopy(ren, tex, nullptr, nullptr);
        SDL_RenderPresent(ren);

        next += 40;                // pace at 25 fps
        uint32_t now = SDL_GetTicks();
        if (next > now)
            SDL_Delay(next - now);
        else
            next = now;
    }

    if (audioDev)
        SDL_CloseAudioDevice(audioDev);
    SDL_Quit();
    delete g_pBoard;
    return 0;
}
