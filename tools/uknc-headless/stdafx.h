/* Minimal Qt-free stdafx.h shim so ukncbtl's emubase core compiles
   standalone for the headless test runner (see main.cpp). */
#pragma once

#include <string.h>
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <assert.h>

typedef char TCHAR;
typedef char *LPTSTR;
typedef const char *LPCTSTR;
#define _T(x)       x
#define _tfopen     fopen
#define _tcscpy     strcpy
#define _tcsrchr    strrchr
#define _tcscmp     strcmp
#define _tcslen     strlen
#define _stricmp    strcasecmp
#define _tcsicmp    _stricmp
#define _snprintf   snprintf
#define _sntprintf  snprintf

#define CALLBACK
typedef void *HANDLE;
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)

/* emubase ASSERTs guard against misbehaving *emulated* programs (odd
   PC, bad addresses).  Never abort the host process for those - warn
   once per site on stderr and carry on, like UKNCBTL release builds
   (which compile ASSERT out entirely). */
#define ASSERT(f) \
    do { if (!(f)) { static bool warned_; if (!warned_) { warned_ = true; \
        fprintf(stderr, "uknc: emubase assertion failed: %s (%s:%d)\n", \
                #f, __FILE__, __LINE__); } } } while (0)
#define VERIFY(f)   ((void)(f))

#define MAKEWORD(a, b) ((uint16_t)(((uint8_t)(((uint32_t)(a)) & 0xff)) | \
                        ((uint16_t)((uint8_t)(((uint32_t)(b)) & 0xff))) << 8))

// Register names used by Disasm.cpp hints (from UKNCBTL's Common.h).
const LPCTSTR REGISTER_NAME[] = { "R0", "R1", "R2", "R3", "R4", "R5", "SP", "PC" };

// Debug logging stubs (the Qt frontend provides real implementations).
inline void DebugLog(LPCTSTR) {}
inline void DebugLogFormat(LPCTSTR, ...) {}
inline void PrintOctalValue(char* buffer, uint16_t value)
{
    for (int p = 0; p < 6; p++)
    {
        int digit = value & 7;
        buffer[5 - p] = (char)('0' + digit);
        value = (uint16_t)(value >> 3);
    }
    buffer[6] = 0;
}
