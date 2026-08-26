/* Minimal SDL2 ABI declarations for uknc-play.cpp.

   The host carries the SDL2 runtime (libSDL2-2.0.so.0) but not the
   dev headers, and the project guideline avoids installing host
   packages.  SDL2's C ABI is stable and documented, so the small
   subset used by the player is declared here by hand and linked
   straight against the runtime library.  Verified against SDL 2.x:
   struct layouts below match the shipped ABI (SDL_Event is 56 bytes;
   we reserve 64). */
#pragma once
#include <stdint.h>

extern "C" {

typedef struct SDL_Window SDL_Window;
typedef struct SDL_Renderer SDL_Renderer;
typedef struct SDL_Texture SDL_Texture;

#define SDL_INIT_AUDIO          0x00000010u
#define SDL_INIT_VIDEO          0x00000020u
#define SDL_WINDOWPOS_CENTERED  0x2FFF0000u
#define SDL_WINDOW_RESIZABLE    0x00000020u
#define SDL_PIXELFORMAT_ARGB8888 0x16362004u
#define SDL_TEXTUREACCESS_STREAMING 1

#define SDL_QUIT_EVENT    0x100
#define SDL_KEYDOWN_EVENT 0x300
#define SDL_KEYUP_EVENT   0x301

/* SDL_Scancode values (USB HID usage ids) */
#define SC_RETURN 40
#define SC_ESCAPE 41
#define SC_TAB    43
#define SC_SPACE  44
#define SC_RIGHT  79
#define SC_LEFT   80
#define SC_DOWN   81
#define SC_UP     82
#define SC_KP_ENTER 88
#define SC_LCTRL  224
#define SC_RCTRL  228
#define SC_1      30   /* ..SC_9 = 38, SC_0 = 39 */
#define SC_0      39

typedef struct { int32_t scancode; int32_t sym; uint16_t mod; uint32_t unused; } SDL_Keysym;
typedef struct {
    uint32_t type, timestamp, windowID;
    uint8_t state, repeat, pad2, pad3;
    SDL_Keysym keysym;
} SDL_KeyboardEvent;
typedef union {
    uint32_t type;
    SDL_KeyboardEvent key;
    uint8_t reserve[64];
} SDL_Event;

int SDL_Init(uint32_t flags);
void SDL_Quit(void);
const char *SDL_GetError(void);
SDL_Window *SDL_CreateWindow(const char *title, int x, int y, int w, int h,
                             uint32_t flags);
SDL_Renderer *SDL_CreateRenderer(SDL_Window *, int index, uint32_t flags);
int SDL_RenderSetLogicalSize(SDL_Renderer *, int w, int h);
SDL_Texture *SDL_CreateTexture(SDL_Renderer *, uint32_t format, int access,
                               int w, int h);
int SDL_UpdateTexture(SDL_Texture *, const void *rect, const void *pixels,
                      int pitch);
int SDL_RenderClear(SDL_Renderer *);
int SDL_RenderCopy(SDL_Renderer *, SDL_Texture *, const void *src,
                   const void *dst);
void SDL_RenderPresent(SDL_Renderer *);
int SDL_PollEvent(SDL_Event *);
uint32_t SDL_GetTicks(void);
void SDL_Delay(uint32_t ms);

/* -- audio (the push interface: SDL_QueueAudio, no callback) -- */
#define AUDIO_S16LSB 0x8010

typedef struct {
    int freq;
    uint16_t format;
    uint8_t channels;
    uint8_t silence;
    uint16_t samples;
    uint16_t padding;
    uint32_t size;
    void (*callback)(void *, uint8_t *, int);
    void *userdata;
} SDL_AudioSpec;

int SDL_InitSubSystem(uint32_t flags);
uint32_t SDL_OpenAudioDevice(const char *device, int iscapture,
                             const SDL_AudioSpec *desired,
                             SDL_AudioSpec *obtained, int allowed_changes);
void SDL_PauseAudioDevice(uint32_t dev, int pause_on);
int SDL_QueueAudio(uint32_t dev, const void *data, uint32_t len);
uint32_t SDL_GetQueuedAudioSize(uint32_t dev);
void SDL_CloseAudioDevice(uint32_t dev);

} /* extern "C" */
