//----------------------------------------------------------------------------
#include "DLLInject.hpp"

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
        if ( localInitFunc )
        {
            localInitFunc( localInitArgs );
        };

        DWORD remoteThreadExitCode;
        ::WaitForSingleObject( remoteThreadHandle, INFINITE );
        ::GetExitCodeThread( remoteThreadHandle, &remoteThreadExitCode );
        ::CloseHandle( remoteThreadHandle );
        return remoteThreadExitCode == 0;
    }
    catch ( std::bad_alloc const & ) { return false; }
    catch ( std::exception const & ) { return false; }
    catch ( ...                    ) { return false; }
}

DWORD replaceIATEntries( HMODULE module, PROC const * original, PROC const * replacement, unsigned int procCount )
{
    BYTE * baseAddress = (BYTE *)module;
    IMAGE_DOS_HEADER * pDOSHeader = (IMAGE_DOS_HEADER *)module;
    IMAGE_NT_HEADERS * pNTHeader = (IMAGE_NT_HEADERS *)(baseAddress + pDOSHeader->e_lfanew);
    IMAGE_OPTIONAL_HEADER * pOptionalHeader = &pNTHeader->OptionalHeader;
    if ( pOptionalHeader->DataDirectory[ IMAGE_DIRECTORY_ENTRY_IMPORT ].Size == 0 )
        return false;

    // Needed for .NET applications.
    if ( pOptionalHeader->DataDirectory[ IMAGE_DIRECTORY_ENTRY_COM_DESCRIPTOR ].VirtualAddress != 0 )
    {
        IMAGE_COR20_HEADER * pCor20Header = (IMAGE_COR20_HEADER *)(baseAddress + \
            pOptionalHeader->DataDirectory[ IMAGE_DIRECTORY_ENTRY_COM_DESCRIPTOR ].VirtualAddress);
        if ( pCor20Header->Flags & COMIMAGE_FLAGS_ILONLY )
        {
            DWORD oldProtect;
            VirtualProtect( &pCor20Header->Flags, sizeof(DWORD), PAGE_READWRITE, &oldProtect );
            pCor20Header->Flags &= ~COMIMAGE_FLAGS_ILONLY;
            VirtualProtect( &pCor20Header->Flags, sizeof(DWORD), oldProtect, &oldProtect );
        }
    }
    IMAGE_IMPORT_DESCRIPTOR * pImportDesc = (IMAGE_IMPORT_DESCRIPTOR*)(baseAddress + 
        pOptionalHeader->DataDirectory[ IMAGE_DIRECTORY_ENTRY_IMPORT ].VirtualAddress );

    DWORD installedHooks = 0;
    // Find the import descriptor containing references 
    // to callee's functions.
    for ( ; ; pImportDesc++ )
    {
        if
        (
            ( pImportDesc->OriginalFirstThunk == 0 ) &&
            ( pImportDesc->TimeDateStamp == 0 ) &&
            ( pImportDesc->ForwarderChain == 0 ) &&
            ( pImportDesc->Name == 0 ) &&
            ( pImportDesc->FirstThunk == 0 )
        )
        {
            // End of the line.
            return installedHooks;
        }

        // Get caller's import address table (IAT) 
        // for the callee's functions.
        PIMAGE_THUNK_DATA pThunk = (PIMAGE_THUNK_DATA) 
            (baseAddress + pImportDesc->FirstThunk);

        PIMAGE_THUNK_DATA pOriginalThunk = (PIMAGE_THUNK_DATA) 
            (baseAddress + pImportDesc->OriginalFirstThunk);

        // Replace current function address with new function address.
        for ( ; pOriginalThunk->u1.Function ; ++pOriginalThunk, ++pThunk )
        {
            for ( DWORD procIndex( 0 ); procIndex < procCount; ++procIndex )
            {
                PROC * ppfn = (PROC *) &pThunk->u1.Function;
                if ( *ppfn != original[ procIndex ] )
                    continue;

                DWORD dwOld;
                VirtualProtect(ppfn, sizeof(PROC *), PAGE_READWRITE, &dwOld);
                *ppfn = replacement[ procIndex ];
                VirtualProtect(ppfn, sizeof(PROC *), dwOld, &dwOld);
                ++installedHooks;
            }
        }
    }
}

int dummyInt;

DWORD hookWinAPI( PROC const * original, PROC const * replacement, unsigned int procCount )
{
    MEMORY_BASIC_INFORMATION mbi;
    VirtualQuery( &dummyInt, &mbi, sizeof(mbi) );
    HMODULE thisModule = (HMODULE)mbi.AllocationBase;

    typedef std::vector<HMODULE> ModuleVec;
    ModuleVec modules( 1024 );
    DWORD size;
    HMODULE exe = ::GetModuleHandle( NULL );
    DWORD replaced = replaceIATEntries( exe, original, replacement, procCount );
    EnumProcessModules( GetCurrentProcess(), modules.data(), modules.size() * sizeof(HMODULE), &size );
    if ( size > modules.size() * sizeof(HMODULE) )
    {
        modules.resize( size / sizeof(HMODULE) );
        EnumProcessModules( GetCurrentProcess(), modules.data(), modules.size() * sizeof(HMODULE), &size );
    }
    else
    {
        modules.resize( size / sizeof(HMODULE) );
    }

    for ( ModuleVec::const_iterator iter( modules.begin() ); iter != modules.end(); ++iter )
    {
        // Do not mess with our import table.
        // We want our hooks to access the original API.
        if ( *iter == thisModule )
            continue;
        replaced += replaceIATEntries( *iter, original, replacement, procCount );
    }
    return replaced;
}


//----------------------------------------------------------------------------
