//----------------------------------------------------------------------------
#include "DLLInject.hpp"

#include <cassert>
#include <stdexcept>
#include <Windows.h>

unsigned char const load32[] = {
    #include "Loader/loader32.inc"
};

unsigned char const load64[] = {
    #include "Loader/loader64.inc"
};

struct AllocProcessMemory
{
    AllocProcessMemory( HANDLE p, DWORD len, DWORD flags = PAGE_READWRITE )
        : p_( p ), len_( len ), offset_( 0 )
    {
        mem_ = (PBYTE)::VirtualAllocEx( p_, NULL, len_, MEM_COMMIT | MEM_RESERVE, flags );
        if ( !mem_ )
            throw std::bad_alloc();
    }

    ~AllocProcessMemory()
    {
        ::VirtualFreeEx( p_, mem_, len_, MEM_DECOMMIT );
    }

    void * get() const { return mem_; }

    void const * get_ptr() const { return &mem_; }

    bool write( void const * data, DWORD len )
    {
        if ( offset_ + len > len_ )
            return false;
        SIZE_T written;
        if ( WriteProcessMemory( p_, mem_ + offset_, data, len, &written ) && ( written == len ) )
        {
            offset_ += len;
            return true;
        }
        return false;
    }

    bool skip( DWORD len )
    {
        if ( offset_ + len > len_ )
            return false;
        offset_ += len;
        return true;
    }

    DWORD offset_;
    HANDLE p_;
    PBYTE mem_;
    DWORD len_;
};

bool injectLibrary( HANDLE const processHandle, HANDLE pipeHandle )
{
    char const currentProcessDLL[] =
#if _WIN64
    "map_files_inj64.dll"
#else
    "map_files_inj32.dll"
#endif
;

    HMODULE currentLoaded;
    BOOL result = GetModuleHandleEx( GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        currentProcessDLL,
        &currentLoaded );
    if ( !result )
        return false;
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
        // No WOW64 - we must be on 32-bit arch
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
        // Injecting code from 32-bit to 64-bit process does not work -
        // eventually CreateRemoteThread() will fail with
        // ERROR_ACCESS_DENIED.
        return false;
    }
#endif

#define FAIL_IF_NOT(expr) if ( !(expr) ) return false
#define FAIL_IF(expr) if ( (expr) ) return false

    try
    {
        AllocProcessMemory dllName( processHandle, moduleNameSize );
        FAIL_IF_NOT( dllName.write( moduleToLoad, moduleNameSize ) );

        char const initFunc[] = "Initialize";
        AllocProcessMemory dllInit( processHandle, sizeof(initFunc) );
        FAIL_IF_NOT( dllInit.write( initFunc, sizeof(initFunc) ) );

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
        AllocProcessMemory funcData( processHandle, loaderCodeLength, PAGE_EXECUTE_READWRITE );
        FAIL_IF_NOT( funcData.write( loaderCode, loaderCodeLength ) );

        // Prepare the parameters
        AllocProcessMemory params( processHandle, targetProcessIs64Bit ? 24 : 12 );

    #ifdef _WIN64
        if ( targetProcessIs64Bit )
        {
            FAIL_IF_NOT( params.write( dllName.get_ptr(), 8 ) );
            FAIL_IF_NOT( params.write( dllInit.get_ptr(), 8 ) );
            FAIL_IF_NOT( params.write( &pipeHandle      , 8 ) );
        }
        else
        {
            // --------------------
            // Should never happen.
            // --------------------
            FAIL_IF( ((UINT_PTR)dllName.get_ptr() & 0xFFFFFFFF00000000) );
            FAIL_IF( ((UINT_PTR)dllInit.get_ptr() & 0xFFFFFFFF00000000) );
            FAIL_IF( ((UINT_PTR)pipeHandle        & 0xFFFFFFFF00000000) );
            // --------------------
            FAIL_IF_NOT( params.write( dllName.get_ptr(), 4 ) );
            FAIL_IF_NOT( params.write( dllInit.get_ptr(), 4 ) );
            FAIL_IF_NOT( params.write( &pipeHandle, 4 ) );
        }
    #else
        FAIL_IF( targetProcessIs64Bit );
        FAIL_IF_NOT( params.write( dllName.get_ptr(), 4 ) );
        FAIL_IF_NOT( params.write( dllInit.get_ptr(), 4 ) );
        FAIL_IF_NOT( params.write( &pipeHandle      , 4 ) );
    #endif

    #undef FAIL_IF
    #undef FAIL_IF_NOT

        // Call the function.
        HANDLE loadLibraryThread = CreateRemoteThread( processHandle, NULL, 0, (LPTHREAD_START_ROUTINE)funcData.get(), params.get(), 0, NULL );
        ::WaitForSingleObject( loadLibraryThread, INFINITE );
        ::GetExitCodeThread( loadLibraryThread, &remoteThreadExitCode );
        return remoteThreadExitCode == 0;
    }
    catch ( std::bad_alloc const & ) { return false; }
    catch ( std::exception const & ) { return false; }
    catch ( ...                    ) { return false; }
}


//----------------------------------------------------------------------------
