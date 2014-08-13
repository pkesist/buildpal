//----------------------------------------------------------------------------
#include "dllInject.hpp"

#include <cassert>
#include <stdexcept>
#include <vector>

#include <Windows.h>
#include <winbase.h>
#include <psapi.h>
#include <shlwapi.h>
#include <winternl.h>

unsigned char const load32[] = {
    #include "Loader/loader32.inc"
};

unsigned char const load64[] = {
    #include "Loader/loader64.inc"
};


HANDLE createRemoteThread( HANDLE processHandle, LPTHREAD_START_ROUTINE func, LPVOID params )
{
    typedef NTSTATUS (NTAPI *RtlCreateUserThreadType) (
        IN HANDLE ProcessHandle,
        IN PSECURITY_DESCRIPTOR SecurityDescriptor,
        IN BOOLEAN CreateSuspended,
        IN ULONG StackZeroBits,
        IN PULONG StackReserved,
        IN PULONG StackCommit,
        IN LPTHREAD_START_ROUTINE StartAddress,
        IN PVOID StartParameter,
        OUT PHANDLE ThreadHandle,
        OUT PVOID ClientID
    );

    static RtlCreateUserThreadType rtlCreateUserThread = (RtlCreateUserThreadType)GetProcAddress( GetModuleHandle( "ntdll.dll" ), "RtlCreateUserThread" );
	HANDLE threadHandle = 0;
    NTSTATUS status = rtlCreateUserThread( processHandle, NULL, TRUE, 0, NULL, NULL, func, params, &threadHandle, NULL );
    return status == 0 ? threadHandle : NULL;
}

HANDLE createRemoteThread_regular( HANDLE processHandle, LPTHREAD_START_ROUTINE func, LPVOID params )
{
    return CreateRemoteThread( processHandle, NULL, 100 * 1024, func, params, 0, NULL ); 
}


struct AllocProcessMemory
{
    AllocProcessMemory( HANDLE p, DWORD len, DWORD flags = PAGE_READWRITE )
        : p_( p ), len_( len ), offset_( 0 ), owned_( true )
    {
        mem_ = (PBYTE)::VirtualAllocEx( p_, NULL, len_, MEM_COMMIT | MEM_RESERVE, flags );
        if ( !mem_ )
            throw std::bad_alloc();
    }

    void * release() { owned_ = false; return get(); }

    ~AllocProcessMemory()
    {
        if ( owned_ )
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
    DWORD owned_;
};

bool injectLibrary( HANDLE const processHandle, char const * dllNames[2],
    char const * initFunc, void * initArgs, InitFunc localInitFunc,
    void * localInitArgs, HANDLE mainThread, bool shouldResume )
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
        std::size_t const ptrSize( targetProcessIs64Bit ? 8 : 4 );

        AllocProcessMemory params( processHandle, 5 * ptrSize );

#ifdef _WIN64
#define GetThreadContext32 Wow64GetThreadContext
#define GetThreadContext64 GetThreadContext
#define SetThreadContext32 Wow64SetThreadContext
#define SetThreadContext64 SetThreadContext
#define SuspendThread32 Wow64SuspendThread
#define SuspendThread64 SuspendThread
#define CONTEXT32 WOW64_CONTEXT
#define CONTEXT64 CONTEXT
#else
#define GetThreadContext32 GetThreadContext
#define SetThreadContext32 SetThreadContext
#define SuspendThread32 SuspendThread
#define CONTEXT32 CONTEXT
#endif
        void * chainFunc = 0;
        void * chainParams = 0;
        // We can inject DLL using main thread if either:
        // 1. The user did not create main thread suspended.
        // 2. There is no init function for the DLL.
        // In case init function exists, then it probably needs to send
        // data to the target process DLL function. We have to do that
        // straight away.
        // This can be improved, but I don't need it ATM, so I don't care.
        bool const injectUsingMainThread = shouldResume || !localInitFunc;

        if ( injectUsingMainThread )
        {
            if ( !targetProcessIs64Bit )
            {
                CONTEXT32 ctx;
                ctx.ContextFlags = CONTEXT_FULL;
                GetThreadContext32( mainThread, &ctx );
                chainFunc = (void *)ctx.Eax;
                chainParams = (void *)ctx.Ebx;
                // TODO: We leak these in the target process.
                // No big deal, but clean it up anyway.
                dllName.release();
                dllInit.release();
                ctx.Eax = (DWORD)funcData.release();
                ctx.Ebx = (DWORD)params.release();
                SetThreadContext32( mainThread, &ctx );
            }
#ifdef _WIN64
            else
            {
                CONTEXT64 ctx;
                ctx.ContextFlags = CONTEXT_FULL;
                GetThreadContext64( mainThread, &ctx );
                chainFunc = (void *)ctx.Rcx;
                chainParams = (void *)ctx.Rdx;
                // TODO: We leak these in the target process.
                // No big deal, but clean it up anyway.
                dllName.release();
                dllInit.release();
                ctx.Rcx = (DWORD)funcData.release();
                ctx.Rdx = (DWORD)params.release();
                SetThreadContext64( mainThread, &ctx );
            }
#endif
        }

    #ifdef _WIN64
        if ( targetProcessIs64Bit )
        {
            FAIL_IF_NOT( params.write( dllName.get_ptr(), 8 ) );
            FAIL_IF_NOT( params.write( dllInit.get_ptr(), 8 ) );
            FAIL_IF_NOT( params.write( &initArgs        , 8 ) );
            FAIL_IF_NOT( params.write( &chainFunc       , 8 ) );
            FAIL_IF_NOT( params.write( &chainParams     , 8 ) );
        }
        else
        {
            // --------------------
            // Should never happen.
            // --------------------
            FAIL_IF( ((UINT_PTR)dllName.get_ptr() & 0xFFFFFFFF00000000) );
            FAIL_IF( ((UINT_PTR)dllInit.get_ptr() & 0xFFFFFFFF00000000) );
            FAIL_IF( ((UINT_PTR)initArgs          & 0xFFFFFFFF00000000) );
            FAIL_IF( ((UINT_PTR)chainFunc         & 0xFFFFFFFF00000000) );
            FAIL_IF( ((UINT_PTR)chainParams       & 0xFFFFFFFF00000000) );
            // --------------------
            FAIL_IF_NOT( params.write( dllName.get_ptr(), 4 ) );
            FAIL_IF_NOT( params.write( dllInit.get_ptr(), 4 ) );
            FAIL_IF_NOT( params.write( &initArgs        , 4 ) );
            FAIL_IF_NOT( params.write( &chainFunc       , 4 ) );
            FAIL_IF_NOT( params.write( &chainParams     , 4 ) );
        }
    #else
        FAIL_IF( targetProcessIs64Bit );
        FAIL_IF_NOT( params.write( dllName.get_ptr(), 4 ) );
        FAIL_IF_NOT( params.write( dllInit.get_ptr(), 4 ) );
        FAIL_IF_NOT( params.write( &initArgs        , 4 ) );
        FAIL_IF_NOT( params.write( &chainFunc       , 4 ) );
        FAIL_IF_NOT( params.write( &chainParams     , 4 ) );
    #endif

    #undef FAIL_IF
    #undef FAIL_IF_NOT


        if ( injectUsingMainThread )
        {
            ResumeThread( mainThread );
            DWORD localInitSuccess = 1;
            if ( localInitFunc )
            {
                localInitSuccess = localInitFunc( localInitArgs );
            };
            return localInitSuccess != 0;
        }
        else
        {
            // Call the function.
            HANDLE const remoteThreadHandle = createRemoteThread( processHandle,
                (LPTHREAD_START_ROUTINE)funcData.get(), params.get() );
            CONTEXT32 ctx;
            ctx.ContextFlags = CONTEXT_FULL;
            GetThreadContext32( remoteThreadHandle, &ctx );
            ResumeThread( remoteThreadHandle );
        
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
                if ( ( remoteThreadExitCode == 0 ) && shouldResume )
                {
                    ResumeThread( mainThread );
                    return true;
                }
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
    }
    catch ( std::bad_alloc const & ) { return false; }
    catch ( std::exception const & ) { return false; }
    catch ( ...                    ) { return false; }
}


//----------------------------------------------------------------------------
