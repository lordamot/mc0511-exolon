/*  uknc-headless -- command-line UKNC (Elektronika MS 0511) emulator runner
    built on the emubase core of UKNCBTL (https://github.com/nzeemin/ukncbtl-qt,
    LGPL v3).  Made for automated build-and-test of the OpenIT MC0511 project:
    boots a raw .dsk image, runs frames, injects keyboard scancodes, takes
    BMP screenshots and reads emulated memory -- all scriptable from stdin
    or a script file, no display required.

    Usage:
        uknc-headless --rom uknc_rom.bin --disk game.dsk [--script file]

    Script commands (one per line; '#' starts a comment):
        run N                 run N frames (50 frames = 1 emulated second)
        press CODE [HOLD]     press+release key, CODE = octal UKNC scancode,
                              HOLD = frames to hold (default 5)
        keydown CODE          press and keep pressed
        keyup CODE            release
        screenshot PATH.bmp   write the 640x288 screen as a 24-bit BMP
        peekw PLAN ADDR       print RAM word (PLAN 0..2, ADDR octal)
        dump PLAN ADDR LEN F  write LEN (decimal) bytes of a plane to file F
        peekcpu ADDR          print a CPU-address-space word (octal addr)
        pokecpu ADDR B...     write octal bytes into CPU address space
        regs                  print CPU and PPU PC/SP
        dumpcpu ADDR LEN F    write LEN bytes of CPU address space to F
        reset                 reset the machine
        wavstart              start capturing speaker audio
        wavstop PATH.wav      stop capture, write 22 kHz mono WAV
        echo TEXT             print TEXT
        quit                  exit
*/

#include "stdafx.h"
#include "Emubase.h"

#include <cctype>
#include <cstdarg>
#include <string>
#include <vector>

static CMotherboard *g_pBoard = nullptr;

// --- WAV capture of the speaker output (22050 Hz mono 16-bit) ---
static std::vector<int16_t> g_wavBuf;
static bool g_wavOn = false;
static void CALLBACK WavCallback(unsigned short L, unsigned short /*R*/)
{
    if (g_wavOn)
        g_wavBuf.push_back((int16_t)((int)L - 16384));
}
static bool WriteWav(const char *path)
{
    FILE *f = fopen(path, "wb");
    if (!f) return false;
    uint32_t dataSize = (uint32_t)(g_wavBuf.size() * 2);
    uint32_t rate = 22050, byteRate = rate * 2;
    uint16_t align = 2, bits = 16, fmt = 1, ch = 1;
    uint32_t riffSize = 36 + dataSize, fmtSize = 16;
    fwrite("RIFF", 1, 4, f); fwrite(&riffSize, 4, 1, f);
    fwrite("WAVEfmt ", 1, 8, f); fwrite(&fmtSize, 4, 1, f);
    fwrite(&fmt, 2, 1, f); fwrite(&ch, 2, 1, f);
    fwrite(&rate, 4, 1, f); fwrite(&byteRate, 4, 1, f);
    fwrite(&align, 2, 1, f); fwrite(&bits, 2, 1, f);
    fwrite("data", 1, 4, f); fwrite(&dataSize, 4, 1, f);
    fwrite(g_wavBuf.data(), 1, dataSize, f);
    fclose(f);
    return true;
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

// Render the current screen into a 640x288 RGB32 buffer.  This is
// Emulator_PrepareScreenRGB32() from UKNCBTL's Emulator.cpp, with Qt
// types replaced by stdint ones.
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

static bool WriteBMP(const char *path, const uint32_t *bits, int w, int h)
{
    FILE *f = fopen(path, "wb");
    if (!f)
        return false;
    int rowbytes = ((w * 3) + 3) & ~3;
    uint32_t datasize = (uint32_t)rowbytes * h;
    uint32_t filesize = 54 + datasize;
    uint8_t hdr[54] = {0};
    hdr[0] = 'B'; hdr[1] = 'M';
    hdr[2] = filesize & 0xFF; hdr[3] = (filesize >> 8) & 0xFF;
    hdr[4] = (filesize >> 16) & 0xFF; hdr[5] = (filesize >> 24) & 0xFF;
    hdr[10] = 54;
    hdr[14] = 40;
    hdr[18] = w & 0xFF; hdr[19] = (w >> 8) & 0xFF;
    hdr[22] = h & 0xFF; hdr[23] = (h >> 8) & 0xFF;
    hdr[26] = 1;
    hdr[28] = 24;
    hdr[34] = datasize & 0xFF; hdr[35] = (datasize >> 8) & 0xFF;
    hdr[36] = (datasize >> 16) & 0xFF; hdr[37] = (datasize >> 24) & 0xFF;
    fwrite(hdr, 1, 54, f);
    std::vector<uint8_t> row(rowbytes, 0);
    for (int y = h - 1; y >= 0; y--)
    {
        for (int x = 0; x < w; x++)
        {
            uint32_t v = bits[y * w + x];
            row[x * 3 + 0] = v & 0xFF;          // B
            row[x * 3 + 1] = (v >> 8) & 0xFF;   // G
            row[x * 3 + 2] = (v >> 16) & 0xFF;  // R
        }
        fwrite(row.data(), 1, rowbytes, f);
    }
    fclose(f);
    return true;
}

static void RunFrames(int n)
{
    for (int i = 0; i < n; i++)
        g_pBoard->SystemFrame();
}

static bool ParseOctal(const char *s, unsigned *out)
{
    unsigned v = 0;
    if (!*s)
        return false;
    for (; *s; s++)
    {
        if (*s < '0' || *s > '7')
            return false;
        v = v * 8 + (unsigned)(*s - '0');
    }
    *out = v;
    return true;
}

static int Fail(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    return 1;
}

static int ExecuteLine(char *line)
{
    // strip comment and split into tokens
    char *hash = strchr(line, '#');
    if (hash)
        *hash = 0;
    std::vector<char*> tok;
    for (char *p = strtok(line, " \t\r\n"); p; p = strtok(nullptr, " \t\r\n"))
        tok.push_back(p);
    if (tok.empty())
        return 0;

    const char *cmd = tok[0];
    if (!strcmp(cmd, "run") && tok.size() >= 2)
    {
        RunFrames(atoi(tok[1]));
    }
    else if (!strcmp(cmd, "runrel") && tok.size() >= 3)
    {
        // runrel ADDR N [MAXTICKS] -- run emulated frames until the CPU
        // word at octal ADDR has advanced by N (decimal), or MAXTICKS
        // frames have passed.  With a frame counter at ADDR this runs
        // the *game* an exact number of frames however slow it is.
        unsigned addr;
        if (!ParseOctal(tok[1], &addr))
            return Fail("bad octal address: %s", tok[1]);
        int n = atoi(tok[2]);
        int maxt = tok.size() >= 4 ? atoi(tok[3]) : n * 8 + 500;
        uint16_t off = (uint16_t)(addr / 2);   // CPU space = planes 1+2
        uint16_t start = (uint16_t)(g_pBoard->GetRAMByte(1, off) |
                                    (g_pBoard->GetRAMByte(2, off) << 8));
        for (int t = 0; t < maxt; t++)
        {
            uint16_t w = (uint16_t)(g_pBoard->GetRAMByte(1, off) |
                                    (g_pBoard->GetRAMByte(2, off) << 8));
            if ((uint16_t)(w - start) >= (uint16_t)n)
                break;
            RunFrames(1);
        }
    }
    else if (!strcmp(cmd, "press") && tok.size() >= 2)
    {
        unsigned code;
        if (!ParseOctal(tok[1], &code))
            return Fail("bad octal scancode: %s", tok[1]);
        int hold = tok.size() >= 3 ? atoi(tok[2]) : 5;
        g_pBoard->KeyboardEvent((uint8_t)code, true);
        RunFrames(hold);
        g_pBoard->KeyboardEvent((uint8_t)code, false);
        RunFrames(3);
    }
    else if (!strcmp(cmd, "keydown") && tok.size() >= 2)
    {
        unsigned code;
        if (!ParseOctal(tok[1], &code))
            return Fail("bad octal scancode: %s", tok[1]);
        g_pBoard->KeyboardEvent((uint8_t)code, true);
    }
    else if (!strcmp(cmd, "keyup") && tok.size() >= 2)
    {
        unsigned code;
        if (!ParseOctal(tok[1], &code))
            return Fail("bad octal scancode: %s", tok[1]);
        g_pBoard->KeyboardEvent((uint8_t)code, false);
    }
    else if (!strcmp(cmd, "screenshot") && tok.size() >= 2)
    {
        std::vector<uint32_t> bits(640 * 288, 0);
        PrepareScreenRGB32(bits.data(), g_colors);
        if (!WriteBMP(tok[1], bits.data(), 640, 288))
            return Fail("cannot write %s", tok[1]);
        printf("screenshot: %s\n", tok[1]);
    }
    else if (!strcmp(cmd, "peekw") && tok.size() >= 3)
    {
        unsigned addr;
        int plan = atoi(tok[1]);
        if (!ParseOctal(tok[2], &addr) || plan < 0 || plan > 2)
            return Fail("usage: peekw PLAN OCTAL-ADDR");
        uint16_t w = g_pBoard->GetRAMWord(plan, (uint16_t)addr);
        printf("peekw %d %06o = %06o (%u)\n", plan, addr, w, w);
    }
    else if (!strcmp(cmd, "dump") && tok.size() >= 5)
    {
        unsigned addr;
        int plan = atoi(tok[1]);
        if (!ParseOctal(tok[2], &addr) || plan < 0 || plan > 2)
            return Fail("usage: dump PLAN OCTAL-ADDR LEN FILE");
        int len = atoi(tok[3]);
        FILE *f = fopen(tok[4], "wb");
        if (!f)
            return Fail("cannot write %s", tok[4]);
        for (int i = 0; i < len; i++)
        {
            uint8_t b = g_pBoard->GetRAMByte(plan, (uint16_t)(addr + i));
            fwrite(&b, 1, 1, f);
        }
        fclose(f);
        printf("dump: %d bytes to %s\n", len, tok[4]);
    }
    else if (!strcmp(cmd, "regs"))
    {
        CProcessor *cpu = g_pBoard->GetCPU();
        CProcessor *ppu = g_pBoard->GetPPU();
        printf("CPU PC=%06o SP=%06o  PPU PC=%06o SP=%06o\n",
               cpu->GetPC(), cpu->GetSP(), ppu->GetPC(), ppu->GetSP());
    }
    else if (!strcmp(cmd, "peekcpu") && tok.size() >= 2)
    {
        // CPU address space: word at A = plane1[A/2] | plane2[A/2] << 8
        unsigned addr;
        if (!ParseOctal(tok[1], &addr))
            return Fail("usage: peekcpu OCTAL-ADDR");
        uint16_t off = (uint16_t)(addr / 2);
        uint16_t w = (uint16_t)(g_pBoard->GetRAMByte(1, off) |
                                (g_pBoard->GetRAMByte(2, off) << 8));
        printf("peekcpu %06o = %06o (%u)\n", addr, w, w);
    }
    else if (!strcmp(cmd, "pokecpu") && tok.size() >= 3)
    {
        // write bytes into CPU address space, starting at ADDR
        unsigned addr;
        if (!ParseOctal(tok[1], &addr))
            return Fail("usage: pokecpu OCTAL-ADDR OCTAL-BYTE...");
        for (size_t i = 2; i < tok.size(); i++)
        {
            unsigned val;
            if (!ParseOctal(tok[i], &val) || val > 0377)
                return Fail("bad octal byte: %s", tok[i]);
            unsigned a = addr + (unsigned)(i - 2);
            g_pBoard->SetRAMByte((a & 1) ? 2 : 1, (uint16_t)(a / 2),
                                 (uint8_t)val);
        }
        printf("pokecpu %06o: %zu byte(s)\n", addr, tok.size() - 2);
    }
    else if (!strcmp(cmd, "dumpcpu") && tok.size() >= 4)
    {
        unsigned addr;
        if (!ParseOctal(tok[1], &addr))
            return Fail("usage: dumpcpu OCTAL-ADDR LEN FILE");
        int len = atoi(tok[2]);
        FILE *f = fopen(tok[3], "wb");
        if (!f)
            return Fail("cannot write %s", tok[3]);
        for (int i = 0; i < len; i++)
        {
            unsigned a = addr + i;
            uint8_t b = g_pBoard->GetRAMByte((a & 1) ? 2 : 1, (uint16_t)(a / 2));
            fwrite(&b, 1, 1, f);
        }
        fclose(f);
        printf("dumpcpu: %d bytes from %06o to %s\n", len, addr, tok[3]);
    }
    else if (!strcmp(cmd, "regs"))
    {
        CProcessor *cpu = g_pBoard->GetCPU();
        CProcessor *ppu = g_pBoard->GetPPU();
        printf("CPU PC=%06o PSW=%06o SP=%06o R0=%06o R1=%06o R2=%06o R3=%06o R4=%06o R5=%06o\n",
               cpu->GetPC(), cpu->GetPSW(), cpu->GetSP(),
               cpu->GetReg(0), cpu->GetReg(1), cpu->GetReg(2),
               cpu->GetReg(3), cpu->GetReg(4), cpu->GetReg(5));
        printf("PPU PC=%06o PSW=%06o SP=%06o  CPUstopped=%d CPUhalt=%d PPUstopped=%d\n",
               ppu->GetPC(), ppu->GetPSW(), ppu->GetSP(),
               (int)cpu->IsStopped(), (int)cpu->IsHaltMode(),
               (int)ppu->IsStopped());
    }
    else if (!strcmp(cmd, "ppuport") && tok.size() >= 2)
    {
        unsigned addr;
        if (!ParseOctal(tok[1], &addr))
            return Fail("usage: ppuport OCTAL-ADDR");
        uint16_t w = g_pBoard->GetPPUMemoryController()->GetPortView((uint16_t)addr);
        printf("ppuport %06o = %06o\n", addr, w);
    }
    else if (!strcmp(cmd, "cputrace") && tok.size() >= 2)
    {
        // Log unique CPU PC transitions over N debug ticks.
        int n = atoi(tok[1]);
        CProcessor *cpu = g_pBoard->GetCPU();
        uint16_t last = 0xFFFF;
        int printed = 0;
        for (int i = 0; i < n && printed < 200; i++)
        {
            g_pBoard->DebugTicks();
            uint16_t pc = cpu->GetPC();
            if (pc != last)
            {
                printf("%06o ", pc);
                if (++printed % 10 == 0) printf("\n");
                last = pc;
            }
        }
        printf("\n");
    }
    else if (!strcmp(cmd, "evnt"))
    {
        g_pBoard->Tick50();
        printf("EVNT ticked\n");
    }
    else if (!strcmp(cmd, "reset"))
    {
        g_pBoard->Reset();
    }
    else if (!strcmp(cmd, "echo"))
    {
        for (size_t i = 1; i < tok.size(); i++)
            printf("%s%s", i > 1 ? " " : "", tok[i]);
        printf("\n");
    }
    else if (!strcmp(cmd, "wavstart"))
    {
        g_wavBuf.clear();
        g_wavOn = true;
        g_pBoard->SetSoundGenCallback(WavCallback);
        printf("wav capture on\n");
    }
    else if (!strcmp(cmd, "wavstop") && tok.size() >= 2)
    {
        g_wavOn = false;
        g_pBoard->SetSoundGenCallback(nullptr);
        if (WriteWav(tok[1]))
            printf("wav: %s (%u samples)\n", tok[1], (unsigned)g_wavBuf.size());
        else
            printf("wav: cannot write %s\n", tok[1]);
    }
    else if (!strcmp(cmd, "quit"))
    {
        return -1;
    }
    else
    {
        return Fail("unknown command: %s", cmd);
    }
    return 0;
}

int main(int argc, char *argv[])
{
    const char *romPath = nullptr;
    const char *diskPath = nullptr;
    const char *scriptPath = nullptr;

    for (int i = 1; i < argc; i++)
    {
        if (!strcmp(argv[i], "--rom") && i + 1 < argc)
            romPath = argv[++i];
        else if (!strcmp(argv[i], "--disk") && i + 1 < argc)
            diskPath = argv[++i];
        else if (!strcmp(argv[i], "--script") && i + 1 < argc)
            scriptPath = argv[++i];
        else
            return Fail("unknown option: %s", argv[i]);
    }
    if (!romPath)
        return Fail("--rom is required (uknc_rom.bin, 32768 bytes)");

    uint8_t rom[32768];
    memset(rom, 0, sizeof(rom));
    FILE *f = fopen(romPath, "rb");
    if (!f)
        return Fail("cannot open ROM %s", romPath);
    size_t n = fread(rom, 1, sizeof(rom), f);
    fclose(f);
    if (n < 16384)
        return Fail("ROM file too small (%zu bytes)", n);

    CProcessor::Init();

    g_pBoard = new CMotherboard();
    g_pBoard->LoadROM(rom);
    // the AY sound module the game's menu option 5 can pick: the core
    // leaves it off, and its three chips answer on the PPU bus at
    // 0177360/2/4
    g_pBoard->SetSoundAY(true);
    g_pBoard->Reset();

    if (diskPath)
    {
        if (!g_pBoard->AttachFloppyImage(0, diskPath))
            return Fail("cannot attach disk %s", diskPath);
    }

    FILE *script = stdin;
    if (scriptPath)
    {
        script = fopen(scriptPath, "r");
        if (!script)
            return Fail("cannot open script %s", scriptPath);
    }

    char line[1024];
    int rc = 0;
    while (fgets(line, sizeof(line), script))
    {
        int r = ExecuteLine(line);
        if (r < 0)
            break;
        if (r > 0)
            rc = r;
        fflush(stdout);
    }

    if (script != stdin)
        fclose(script);
    delete g_pBoard;
    return rc;
}
