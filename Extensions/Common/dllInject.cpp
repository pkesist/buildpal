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

    void * write( void const * data, DWORD len )
    {
        if ( offset_ + len > len_ )
            return 0;
        SIZE_T written;
        if ( WriteProcessMemory( p_, mem_ + offset_, data, len, &written ) && ( written == len ) )
        {
            offset_ += len;
            return mem_ + offset_ - len;
        }
        return 0;
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
    void * localInitArgs, HANDLE mainThread, bool resumeAfterInitialization )
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
        DWORD const initFuncLen = strlen(initFunc);
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

        AllocProcessMemory memoryBlock( processHandle,
            moduleNameSize + 1 +
            initFuncLen + 1 +
            loaderCodeLength,
            PAGE_EXECUTE_READWRITE
        );
        void * dllName( memoryBlock.write( moduleToLoad, moduleNameSize + 1 ) );
        FAIL_IF_NOT( dllName );

        void * dllInit( memoryBlock.write( initFunc, initFuncLen + 1 ) );
        FAIL_IF_NOT( dllInit );

        void * funcData( memoryBlock.write( loaderCode, loaderCodeLength ) );
        FAIL_IF_NOT( funcData );

        // Prepare the parameters
        std::size_t const ptrSize( targetProcessIs64Bit ? 8 : 4 );
        AllocProcessMemory params( processHandle, 6 * ptrSize );

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
        HANDLE initDoneEvent = NULL;
        HANDLE initDoneCopy = NULL;
        
        if ( !resumeAfterInitialization )
        {
            initDoneEvent = CreateEvent( NULL, TRUE, FALSE, NULL );
            DuplicateHandle( GetCurrentProcess(), initDoneEvent,
                processHandle, &initDoneCopy, 0, FALSE,
                DUPLICATE_SAME_ACCESS );
        }

        if ( targetProcessIs64Bit )
        {
#ifdef _WIN64
            CONTEXT64 ctx;
            ctx.ContextFlags = CONTEXT_FULL;
            GetThreadContext64( mainThread, &ctx );
            void * chainFunc = (void *)ctx.Rcx;
            void * chainParams = (void *)ctx.Rdx;
            memoryBlock.release();
            ctx.Rcx = (DWORD)funcData;
            ctx.Rdx = (DWORD)params.release();
            SetThreadContext64( mainThread, &ctx );

            FAIL_IF_NOT( params.write( &dllName     , 8 ) );
            FAIL_IF_NOT( params.write( &dllInit     , 8 ) );
            FAIL_IF_NOT( params.write( &initArgs    , 8 ) );
            FAIL_IF_NOT( params.write( &chainFunc   , 8 ) );
            FAIL_IF_NOT( params.write( &chainParams , 8 ) );
            FAIL_IF_NOT( params.write( &initDoneCopy, 8 ) );
#else
            return false;
#endif
        }
        else
        {
            CONTEXT32 ctx;
            ctx.ContextFlags = CONTEXT_FULL;
            GetThreadContext32( mainThread, &ctx );
            void * chainFunc = (void *)ctx.Eax;
            void * chainParams = (void *)ctx.Ebx;
            memoryBlock.release();
            ctx.Eax = (DWORD)funcData;
            ctx.Ebx = (DWORD)params.release();
            SetThreadContext32( mainThread, &ctx );
            // Works for both 32 and 64 bit arch (LE).
            FAIL_IF_NOT( params.write( &dllName     , 4 ) );
            FAIL_IF_NOT( params.write( &dllInit     , 4 ) );
            FAIL_IF_NOT( params.write( &initArgs    , 4 ) );
            FAIL_IF_NOT( params.write( &chainFunc   , 4 ) );
            FAIL_IF_NOT( params.write( &chainParams , 4 ) );
            FAIL_IF_NOT( params.write( &initDoneCopy, 4 ) );
        }

#undef FAIL_IF
#undef FAIL_IF_NOT

        // Resume the main thread. It will suspend itself if needeed when it is
        // done with DLL initialization (if the initialization function respects
        // the suspended flag).
        ResumeThread( mainThread );
        bool localInitResult = true;
        if ( localInitFunc )
            localInitResult = localInitFunc( localInitArgs ) == 0;
        if ( initDoneEvent )
        {
            WaitForSingleObject( initDoneEvent, INFINITE );
            SuspendThread( mainThread );
            SetEvent( initDoneEvent );
            CloseHandle( initDoneEvent );
        }
        return localInitResult;
    }
    catch ( std::bad_alloc const & ) { return false; }
    catch ( std::exception const & ) { return false; }
    catch ( ...                    ) { return false; }
}


//----------------------------------------------------------------------------
