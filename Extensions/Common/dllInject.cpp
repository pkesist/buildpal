//----------------------------------------------------------------------------
#include "dllInject.hpp"

#include <cassert>
#include <stdexcept>
#include <vector>

#include <Windows.h>
#include <psapi.h>
#include <shlwapi.h>

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

bool injectLibrary( HANDLE const processHandle, char const * dllNames[2],
    char const * initFunc, void * initArgs, InitFunc localInitFunc,
    void * localInitArgs )
{
    HMODULE currentLoaded;
    BOOL result = GetModuleHandleEx( GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
#if _WIN64
        dllNames[1],
#else
        dllNames[0],
#endif
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
        // We have to inject 32-bit version. We assume it is in the same dir as
        // currently loaded 64-bit version.
        std::strcpy( moduleToLoad + moduleNameSize - strlen(dllNames[1]), dllNames[0] );
    }
#else
    if ( targetProcessIs64Bit )
    {
        // Injecting code from 32-bit to 64-bit process does not work -
        // eventually CreateRemoteThread() will fail with
        // ERROR_ACCESS_DENIED.
        // Note that it is possible to do this, but YAGNI.
        return false;
    }
#endif

#define FAIL_IF_NOT(expr) if ( !(expr) ) return false
#define FAIL_IF(expr) if ( (expr) ) return false

    try
    {
        AllocProcessMemory dllName( processHandle, moduleNameSize );
        FAIL_IF_NOT( dllName.write( moduleToLoad, moduleNameSize ) );

        DWORD const initFuncLen = strlen(initFunc);
        AllocProcessMemory dllInit( processHandle, initFuncLen );
        FAIL_IF_NOT( dllInit.write( initFunc, initFuncLen ) );

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
            FAIL_IF_NOT( params.write( &initArgs        , 8 ) );
        }
        else
        {
            // --------------------
            // Should never happen.
            // --------------------
            FAIL_IF( ((UINT_PTR)dllName.get_ptr() & 0xFFFFFFFF00000000) );
            FAIL_IF( ((UINT_PTR)dllInit.get_ptr() & 0xFFFFFFFF00000000) );
            FAIL_IF( ((UINT_PTR)initArgs          & 0xFFFFFFFF00000000) );
            // --------------------
            FAIL_IF_NOT( params.write( dllName.get_ptr(), 4 ) );
            FAIL_IF_NOT( params.write( dllInit.get_ptr(), 4 ) );
            FAIL_IF_NOT( params.write( &initArgs        , 4 ) );
        }
    #else
        FAIL_IF( targetProcessIs64Bit );
        FAIL_IF_NOT( params.write( dllName.get_ptr(), 4 ) );
        FAIL_IF_NOT( params.write( dllInit.get_ptr(), 4 ) );
        FAIL_IF_NOT( params.write( &initArgs        , 4 ) );
    #endif

    #undef FAIL_IF
    #undef FAIL_IF_NOT

        // Call the function.
        HANDLE const remoteThreadHandle = CreateRemoteThread( processHandle,
            NULL, 0, (LPTHREAD_START_ROUTINE)funcData.get(), params.get(), 0,
            NULL );
        
        DWORD localInitSuccess = 1;
        if ( localInitFunc )
        {
            localInitSuccess = localInitFunc( localInitArgs );
        };

        if ( localInitSuccess )
        {
            DWORD remoteThreadExitCode;
            ::WaitForSingleObject( remoteThreadHandle, INFINITE );
            ::GetExitCodeThread( remoteThreadHandle, &remoteThreadExitCode );
            ::CloseHandle( remoteThreadHandle );
            return remoteThreadExitCode == 0;
        }
        else
        {
            DWORD result = ::WaitForSingleObject( remoteThreadHandle, 500 );
            if ( result == WAIT_TIMEOUT )
            {
                TerminateThread( remoteThreadHandle, (DWORD)-1 );
            }
            CloseHandle( remoteThreadHandle );
            return false;
        }
    }
    catch ( std::bad_alloc const & ) { return false; }
    catch ( std::exception const & ) { return false; }
    catch ( ...                    ) { return false; }
}


//----------------------------------------------------------------------------
