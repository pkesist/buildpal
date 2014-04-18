//----------------------------------------------------------------------------
#include "DLLInject.hpp"

#include <cassert>
#include <Windows.h>

unsigned char const load32[] = {
    #include "Loader/loader32.inc"
};

unsigned char const load64[] = {
    #include "Loader/loader64.inc"
};

bool injectLibrary( HANDLE const processHandle, HANDLE pipeHandle )
{
    char const currentInjectDLL[] =
#if _WIN64
    "map_files_inj64.dll"
#else
    "map_files_inj32.dll"
#endif
;

    HMODULE currentLoaded;
    BOOL result = GetModuleHandleEx( GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        currentInjectDLL,
        &currentLoaded );
    assert( result );
    char moduleToLoad[ MAX_PATH ];
    DWORD const moduleNameSize = GetModuleFileName( currentLoaded, moduleToLoad, MAX_PATH );

    typedef BOOL (WINAPI * ISWOW64)(HANDLE, PBOOL);
    ISWOW64 fnIsWow64 = (ISWOW64)GetProcAddress(
        GetModuleHandle("Kernel32"), "IsWow64Process" );

    bool targetProcessIs64Bit = false;
    if ( fnIsWow64 )
    {
        BOOL tempBool;
#ifdef _WIN64
        bool const osIs64Bit = true;
#else
        bool const osIs64Bit = fnIsWow64( GetCurrentProcess(), &tempBool ) && tempBool;
#endif
        if ( osIs64Bit )
        {
            targetProcessIs64Bit = !(fnIsWow64( processHandle, &tempBool ) && tempBool);
        }
    }
    else
    {
        // No WOW64 - we must be on 32-bit
    }

#ifdef _WIN64
    if ( !targetProcessIs64Bit )
    {
        moduleToLoad[ moduleNameSize - 6 ] = '3';
        moduleToLoad[ moduleNameSize - 5 ] = '2';
    }
#else
    if ( targetProcessIs64Bit )
    {
        // Does not work - eventually CreateRemoteThread() will fail with
        // ERROR_ACCESS_DENIED.
        return false;
    }
#endif

    SIZE_T written;
    void * dllName = ::VirtualAllocEx( processHandle, NULL, moduleNameSize, MEM_COMMIT, PAGE_READWRITE );
    ::WriteProcessMemory( processHandle, dllName, moduleToLoad, moduleNameSize, &written );
    assert( written == moduleNameSize );

    char const initFunc[] = "Initialize";
    void * dllInit = ::VirtualAllocEx( processHandle, NULL, sizeof(initFunc), MEM_COMMIT, PAGE_READWRITE );
    ::WriteProcessMemory( processHandle, dllInit, initFunc, sizeof(initFunc), &written );
    assert( written == sizeof(initFunc) );

    unsigned char const * loaderCode;
    unsigned int loaderCodeLength;
    if ( targetProcessIs64Bit )
    {
        loaderCode = load64;
        loaderCodeLength = sizeof(load64);
    }
    else
    {
        loaderCode = load32;
        loaderCodeLength = sizeof(load32);
    }

    DWORD remoteThreadExitCode;
    // Prepare the function
    void * funcData = VirtualAllocEx( processHandle, NULL, loaderCodeLength, MEM_COMMIT, PAGE_EXECUTE_READWRITE );
    WriteProcessMemory( processHandle, funcData, loaderCode, loaderCodeLength, &written );
    assert( written == loaderCodeLength );

    // Prepare the parameters
    PBYTE params = (PBYTE)VirtualAllocEx( processHandle, NULL, targetProcessIs64Bit ? 24 : 12, MEM_COMMIT, PAGE_READWRITE );

#ifdef _WIN64
    if ( targetProcessIs64Bit )
    {
        WriteProcessMemory( processHandle, params + 0 * 8, &dllName   , 8, &written );
        assert( written == 8 );
        WriteProcessMemory( processHandle, params + 1 * 8, &dllInit   , 8, &written );
        assert( written == 8 );
        WriteProcessMemory( processHandle, params + 2 * 8, &pipeHandle, 8, &written );
        assert( written == 8 );
    }
    else
    {
        assert( !((UINT_PTR)dllName    & 0xFFFFFFFF00000000) );
        assert( !((UINT_PTR)dllInit    & 0xFFFFFFFF00000000) );
        assert( !((UINT_PTR)pipeHandle & 0xFFFFFFFF00000000) );
        WriteProcessMemory( processHandle, params + 0 * 4, &dllName, 4, &written );
        assert( written == 4 );
        WriteProcessMemory( processHandle, params + 1 * 4, &dllInit, 4, &written );
        assert( written == 4 );
        WriteProcessMemory( processHandle, params + 2 * 4, &pipeHandle, 4, &written );
        assert( written == 4 );
    }
#else
    assert( !targetProcessIs64Bit );
    WriteProcessMemory( processHandle, params + 0 * 4, &dllName   , 4, &written );
    assert( written == 8 );
    WriteProcessMemory( processHandle, params + 1 * 4, &dllInit   , 4, &written );
    assert( written == 8 );
    WriteProcessMemory( processHandle, params + 2 * 4, &pipeHandle, 4, &written );
    assert( written == 8 );
#endif

    // Call the function.
    HANDLE loadLibraryThread = CreateRemoteThread( processHandle, NULL, 0, (LPTHREAD_START_ROUTINE)funcData, params, 0, NULL );
    ::WaitForSingleObject( loadLibraryThread, INFINITE );
    ::GetExitCodeThread( loadLibraryThread, &remoteThreadExitCode );
    ::VirtualFreeEx( processHandle, dllName, moduleNameSize, MEM_DECOMMIT );
    ::VirtualFreeEx( processHandle, dllInit, sizeof(initFunc), MEM_DECOMMIT );
    ::VirtualFreeEx( processHandle, funcData, targetProcessIs64Bit ? 24 : 12, MEM_DECOMMIT );
    return remoteThreadExitCode == 0;
}


//----------------------------------------------------------------------------
