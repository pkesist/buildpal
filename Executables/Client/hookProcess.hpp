//------------------------------------------------------------------------------
#ifndef hookProcess_HPP__650DBA06_5BC9_41C5_9242_C39C79C17AFD
#define hookProcess_HPP__650DBA06_5BC9_41C5_9242_C39C79C17AFD
//------------------------------------------------------------------------------
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

BOOL WINAPI createProcessA(
    char const * lpApplicationName,
    char * lpCommandLine,
    LPSECURITY_ATTRIBUTES lpProcessAttributes,
    LPSECURITY_ATTRIBUTES lpThreadAttributes,
    BOOL bInheritHandles,
    DWORD dwCreationFlags,
    LPVOID lpEnvironment,
    char const * lpCurrentDirectory,
    LPSTARTUPINFOA lpStartupInfo,
    LPPROCESS_INFORMATION lpProcessInformation
);
BOOL WINAPI createProcessW(
    wchar_t const * lpApplicationName,
    wchar_t * lpCommandLine,
    LPSECURITY_ATTRIBUTES lpProcessAttributes,
    LPSECURITY_ATTRIBUTES lpThreadAttributes,
    BOOL bInheritHandles,
    DWORD dwCreationFlags,
    LPVOID lpEnvironment,
    wchar_t const * lpCurrentDirectory,
    LPSTARTUPINFOW lpStartupInfo,
    LPPROCESS_INFORMATION lpProcessInformation
);


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
