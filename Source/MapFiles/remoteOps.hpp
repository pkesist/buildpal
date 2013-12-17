//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef remoteOps_HPP__704B418B_095E_40D4_A136_70A02E103918
#define remoteOps_HPP__704B418B_095E_40D4_A136_70A02E103918
//------------------------------------------------------------------------------
#include <windows.h>
//------------------------------------------------------------------------------

HMODULE WINAPI GetRemoteModuleHandle( HANDLE hProcess, char const * moduleName );

PROC WINAPI GetRemoteProcAddress(
    HANDLE hProcess,
    HMODULE hModule,
    char const * lpProcName,
    unsigned int ordinal = 0,
    bool useOrdinal = false);


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
