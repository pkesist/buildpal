#include "mapFilesInject.hpp"

#include "DLLInject.hpp"

#include <boost/locale/conversion.hpp>
#include <boost/locale/generator.hpp>

#include <cassert>
#include <iostream>
#include <string>
#include <codecvt>
#include <locale>

#include <windows.h>
#include <psapi.h>
#include <shlwapi.h>

HMODULE WINAPI hookLoadLibraryA( char * );
HMODULE WINAPI hookLoadLibraryW( wchar_t * );

FileMapping fileMapping;
HMODULE thisModule;

namespace
{
    bool readMapping( HANDLE readHandle, std::string & f, std::string & s )
    {
        BOOL success;
        DWORD read;
        unsigned char sizes[4];
        success = ReadFile( readHandle, sizes, 4, &read, 0 );
        assert( success );
        assert( read == 4 );
        std::size_t const firstSize = ( sizes[1] << 8 ) + sizes[0];
        std::size_t const secondSize = ( sizes[3] << 8 ) + sizes[2];
        if ( firstSize == 0 || secondSize == 0 )
            return false;
        std::string first;
        first.resize( firstSize );
        success = ReadFile( readHandle, &first[0], firstSize, &read, 0 );
        assert( success );
        assert( read == firstSize );
        std::string second;
        second.resize( secondSize );
        success = ReadFile( readHandle, &second[0], secondSize, &read, 0 );
        assert( success );
        assert( read == secondSize );
        f.swap( first );
        s.swap( second );
        return true;
    }

    void writeMapping( HANDLE writeHandle, std::string const & first, std::string const & second )
    {
        assert( first.size() < 0xFFFF );
        assert( second.size() < 0xFFFF );
        char sizes[4];
        sizes[0] = first.size() & 0xFF;
        sizes[1] = first.size() >> 8;
        sizes[2] = second.size() & 0xFF;
        sizes[3] = second.size() >> 8;
        DWORD written;
        BOOL result;
        result = WriteFile( writeHandle, sizes, 4, &written, 0 );
        assert( result );
        assert( written == 4 );
        result = WriteFile( writeHandle, first.data(), first.size(), &written, 0 );
        assert( result );
        assert( written == first.size() );
        result = WriteFile( writeHandle, second.data(), second.size(), &written, 0 );
        assert( result );
        assert( written == second.size() );
    };

    void writeEnd( HANDLE writeHandle )
    {
        char end[4] = { 0 };
        DWORD written;
        BOOL result;
        result = WriteFile( writeHandle, end, 4, &written, 0 );
        assert( result );
        assert( written == 4 );
    }

    void hookProcess( HANDLE processHandle )
    {
	    DLLInjector dllInjector( ::GetProcessId( processHandle ) );
        HANDLE pipeRead;
        HANDLE pipeWrite;
        BOOL result;
        // Shared memory would be better.
        result = CreatePipe( &pipeRead, &pipeWrite, 0, 0 );
        assert( result );
        HANDLE targetRead;
        result = DuplicateHandle( GetCurrentProcess(), pipeRead,
            processHandle, &targetRead, 0, FALSE,
            DUPLICATE_SAME_ACCESS | DUPLICATE_CLOSE_SOURCE );
        assert( result );
        
        for ( FileMapping::value_type const & filePair : fileMapping )
            writeMapping( pipeWrite, filePair.first, filePair.second );
        writeEnd( pipeWrite );

        DWORD overrideResult = dllInjector.callRemoteProc( "overrideFiles__internal", targetRead );
        assert( overrideResult == 0 );
        CloseHandle( pipeWrite );
        DWORD hookResult = dllInjector.callRemoteProc( "hookWinAPIs", 0 );
        assert( hookResult == 0 );
    }

    std::string normalizePath( std::string const & path )
    {
        std::string tmp( path );
        for ( char & c : tmp )
            if ( c == '/' )
                c = '\\';
        char buffer[4 * MAX_PATH];
        BOOL result = PathCanonicalize( buffer, tmp.c_str() );
        assert( result );
        char const * ptr = buffer;
        if ( *ptr == '\\' )
            ++ptr;
        boost::locale::generator gen;
        std::locale locale = gen("en_US.UTF-8");
        return boost::locale::normalize(
            boost::locale::to_lower( ptr, locale ),
            boost::locale::norm_default,
            locale
        );
    }
}

HANDLE WINAPI hookCreateFileA(
  _In_      char const * lpFileName,
  _In_      DWORD dwDesiredAccess,
  _In_      DWORD dwShareMode,
  _In_opt_  LPSECURITY_ATTRIBUTES lpSecurityAttributes,
  _In_      DWORD dwCreationDisposition,
  _In_      DWORD dwFlagsAndAttributes,
  _In_opt_  HANDLE hTemplateFile
)
{
    FileMapping::const_iterator const iter = fileMapping.find( normalizePath( lpFileName ) );
    return CreateFileA( iter == fileMapping.end() ? lpFileName : iter->second.c_str(),
        dwDesiredAccess,
        dwShareMode,
        lpSecurityAttributes,
        dwCreationDisposition,
        dwFlagsAndAttributes,
        hTemplateFile
    );
}

HANDLE WINAPI hookCreateFileW(
  _In_      wchar_t const * lpFileName,
  _In_      DWORD dwDesiredAccess,
  _In_      DWORD dwShareMode,
  _In_opt_  LPSECURITY_ATTRIBUTES lpSecurityAttributes,
  _In_      DWORD dwCreationDisposition,
  _In_      DWORD dwFlagsAndAttributes,
  _In_opt_  HANDLE hTemplateFile
)
{
    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    FileMapping::const_iterator const iter = fileMapping.find(
        normalizePath( convert.to_bytes( lpFileName ) ) );
    return CreateFileW
    ( 
        iter == fileMapping.end() ? lpFileName : convert.from_bytes( iter->second ).c_str(),
        dwDesiredAccess,
        dwShareMode,
        lpSecurityAttributes,
        dwCreationDisposition,
        dwFlagsAndAttributes,
        hTemplateFile
    );
}

extern "C" BOOL WINAPI createProcessWithOverridesA(
  _In_opt_     char const * lpApplicationName,
  _Inout_opt_  char * lpCommandLine,
  _In_opt_     LPSECURITY_ATTRIBUTES lpProcessAttributes,
  _In_opt_     LPSECURITY_ATTRIBUTES lpThreadAttributes,
  _In_         BOOL bInheritHandles,
  _In_         DWORD dwCreationFlags,
  _In_opt_     LPVOID lpEnvironment,
  _In_opt_     char const * lpCurrentDirectory,
  _In_         LPSTARTUPINFOA lpStartupInfo,
  _Out_        LPPROCESS_INFORMATION lpProcessInformation,
               FileMapping const & fileMapping
)
{
    bool const shouldResume = (dwCreationFlags & CREATE_SUSPENDED) == 0;
    BOOL result = CreateProcessA(
        lpApplicationName,
        lpCommandLine,
        lpProcessAttributes,
        lpThreadAttributes,
        bInheritHandles,
        dwCreationFlags | ( fileMapping.empty() ? 0 : CREATE_SUSPENDED ),
        lpEnvironment,
        lpCurrentDirectory,
        lpStartupInfo,
        lpProcessInformation);
    if ( !fileMapping.empty() && result )
    {
        hookProcess( lpProcessInformation->hProcess );
        if ( shouldResume )
            ResumeThread( lpProcessInformation->hThread );
    }
    return result;
}

extern "C" BOOL WINAPI createProcessWithOverridesW(
  _In_opt_     wchar_t const * lpApplicationName,
  _Inout_opt_  wchar_t * lpCommandLine,
  _In_opt_     LPSECURITY_ATTRIBUTES lpProcessAttributes,
  _In_opt_     LPSECURITY_ATTRIBUTES lpThreadAttributes,
  _In_         BOOL bInheritHandles,
  _In_         DWORD dwCreationFlags,
  _In_opt_     LPVOID lpEnvironment,
  _In_opt_     wchar_t const * lpCurrentDirectory,
  _In_         LPSTARTUPINFOW lpStartupInfo,
  _Out_        LPPROCESS_INFORMATION lpProcessInformation,
               FileMapping const & fileMapping
)
{
    bool const shouldResume = (dwCreationFlags & CREATE_SUSPENDED) == 0;
    BOOL result = CreateProcessW(
        lpApplicationName,
        lpCommandLine,
        lpProcessAttributes,
        lpThreadAttributes,
        bInheritHandles,
        dwCreationFlags | ( fileMapping.empty() ? 0 : CREATE_SUSPENDED ),
        lpEnvironment,
        lpCurrentDirectory,
        lpStartupInfo,
        lpProcessInformation);
    if ( !fileMapping.empty() && result )
    {
        hookProcess( lpProcessInformation->hProcess );
        if ( shouldResume )
            ResumeThread( lpProcessInformation->hThread );
    }
    return result;
}

extern "C" BOOL WINAPI createProcessWithFSHookA(
  _In_opt_     char const * lpApplicationName,
  _Inout_opt_  char * lpCommandLine,
  _In_opt_     LPSECURITY_ATTRIBUTES lpProcessAttributes,
  _In_opt_     LPSECURITY_ATTRIBUTES lpThreadAttributes,
  _In_         BOOL bInheritHandles,
  _In_         DWORD dwCreationFlags,
  _In_opt_     LPVOID lpEnvironment,
  _In_opt_     char const * lpCurrentDirectory,
  _In_         LPSTARTUPINFO lpStartupInfo,
  _Out_        LPPROCESS_INFORMATION lpProcessInformation
)
{
    return createProcessWithOverridesA( lpApplicationName, lpCommandLine,
        lpProcessAttributes, lpThreadAttributes, bInheritHandles,
        dwCreationFlags, lpEnvironment, lpCurrentDirectory,
        lpStartupInfo, lpProcessInformation, fileMapping );
}

extern "C" BOOL WINAPI createProcessWithFSHookW(
  _In_opt_     wchar_t const * lpApplicationName,
  _Inout_opt_  wchar_t * lpCommandLine,
  _In_opt_     LPSECURITY_ATTRIBUTES lpProcessAttributes,
  _In_opt_     LPSECURITY_ATTRIBUTES lpThreadAttributes,
  _In_         BOOL bInheritHandles,
  _In_         DWORD dwCreationFlags,
  _In_opt_     LPVOID lpEnvironment,
  _In_opt_     wchar_t const * lpCurrentDirectory,
  _In_         LPSTARTUPINFOW lpStartupInfo,
  _Out_        LPPROCESS_INFORMATION lpProcessInformation
)
{
    return createProcessWithOverridesW( lpApplicationName, lpCommandLine,
        lpProcessAttributes, lpThreadAttributes, bInheritHandles,
        dwCreationFlags, lpEnvironment, lpCurrentDirectory,
        lpStartupInfo, lpProcessInformation, fileMapping );
}


HMODULE WINAPI hookLoadLibraryA( char * lpFileName )
{
    HMODULE result = ::LoadLibraryA( lpFileName );
    hookWinAPIs(0);
    return result;
}

HMODULE WINAPI hookLoadLibraryW( wchar_t * lpFileName )
{
    HMODULE result = ::LoadLibraryW( lpFileName );
    hookWinAPIs(0);
    return result;
}

static bool replaceEntry( char const * const pszCalleeModName, char const * const funcName, PROC pfnNew, HMODULE hmodCaller )
{
    IMAGE_DOS_HEADER * pDOSHeader = (IMAGE_DOS_HEADER *)hmodCaller; 
    IMAGE_OPTIONAL_HEADER * pOptionHeader = (IMAGE_OPTIONAL_HEADER*)((BYTE*)hmodCaller + pDOSHeader->e_lfanew + 24);
    if ( pOptionHeader->DataDirectory[ IMAGE_DIRECTORY_ENTRY_IMPORT ].Size == 0 )
        return false;
    IMAGE_IMPORT_DESCRIPTOR * pImportDesc = (IMAGE_IMPORT_DESCRIPTOR*)((BYTE*)hmodCaller + 
        pOptionHeader->DataDirectory[ IMAGE_DIRECTORY_ENTRY_IMPORT ].VirtualAddress );
    // Find the import descriptor containing references 
    // to callee's functions.
    for (; pImportDesc->Name; pImportDesc++)
    {
        PSTR pszModName = (PSTR)((PBYTE) hmodCaller + pImportDesc->Name);
        if ( lstrcmpiA(pszModName, pszCalleeModName) == 0 ) 
            break;
    }

    if ( pImportDesc->Name == 0 )
        // This module doesn't import any functions from this callee.
        return false; 

    // Get caller's import address table (IAT) 
    // for the callee's functions.
    PIMAGE_THUNK_DATA pThunk = (PIMAGE_THUNK_DATA) 
        ((PBYTE) hmodCaller + pImportDesc->FirstThunk);

    PIMAGE_THUNK_DATA pOriginalThunk = (PIMAGE_THUNK_DATA) 
        ((PBYTE) hmodCaller + pImportDesc->OriginalFirstThunk);

     // Replace current function address with new function address.
     for ( ; pOriginalThunk->u1.Function; pThunk++, pOriginalThunk++ )
     {
         char const * pName = (char *)((PBYTE)hmodCaller + pOriginalThunk->u1.AddressOfData + 2);
         if ( _stricmp( funcName, pName ) == 0 )
         {
             PROC * ppfn = (PROC *) &pThunk->u1.Function;
             DWORD dwOld;
             BOOL result;
             result = VirtualProtect(ppfn, 4, PAGE_READWRITE, &dwOld);
             assert( result );
             *ppfn = pfnNew;
             result = VirtualProtect(ppfn, 4, PAGE_EXECUTE, &dwOld);
             assert( result );
             return true;  // We did it; get out.
          }
      }
    // If we get to here, the function
    // is not in the caller's import section.
    return false;
}

DWORD hookWinAPI( char const * calleeName, char const * funcName, PROC newProc )
{
    HMODULE modules[ 1024 ];
    DWORD size;
    HMODULE exe = ::GetModuleHandle( NULL );
    DWORD replaced = 0;
    if ( replaceEntry( calleeName, funcName, newProc, exe ) )
        replaced++;
    if ( EnumProcessModules( GetCurrentProcess(), modules, sizeof( modules ), &size ) )
    {
        unsigned int len = size / sizeof( HMODULE );
        for ( unsigned int index( 0 ); index < len; ++index )
        {
            if ( modules[ index ] == thisModule )
                continue;
            if ( replaceEntry( calleeName, funcName, newProc, modules[ index ] ) )
                replaced++;
        }
    }
    return replaced;
}

extern "C" DWORD WINAPI hookWinAPIs( void * )
{
    hookWinAPI( "Kernel32.dll", "CreateFileA", (PROC)hookCreateFileA );
    hookWinAPI( "Kernel32.dll", "CreateFileW", (PROC)hookCreateFileW );
    hookWinAPI( "Kernel32.dll", "LoadLibraryA", (PROC)hookLoadLibraryA );
    hookWinAPI( "Kernel32.dll", "LoadLibraryW", (PROC)hookLoadLibraryW );
    hookWinAPI( "Kernel32.dll", "CreateProcessA", (PROC)createProcessWithFSHookA );
    hookWinAPI( "Kernel32.dll", "CreateProcessW", (PROC)createProcessWithFSHookW );
    return 0;
}

extern "C" DWORD WINAPI unhookWinAPIs( void * )
{
	HMODULE kernelModule( ::GetModuleHandle( "Kernel32.dll" ) );
	hookWinAPI( "Kernel32.dll", "CreateFileA", ::GetProcAddress( kernelModule, "CreateFileA" ) );
    hookWinAPI( "Kernel32.dll", "CreateFileW", ::GetProcAddress( kernelModule, "CreateFileW" ) );
    hookWinAPI( "Kernel32.dll", "LoadLibraryA", ::GetProcAddress( kernelModule, "LoadLibraryA" ) );
    hookWinAPI( "Kernel32.dll", "LoadLibraryW", ::GetProcAddress( kernelModule, "LoadLibraryW" ) );
    hookWinAPI( "Kernel32.dll", "CreateProcessA", ::GetProcAddress( kernelModule, "CreateProcessA" ) );
    hookWinAPI( "Kernel32.dll", "CreateProcessW", ::GetProcAddress( kernelModule, "CreateProcessW" ) );
    return 0;
}

extern "C" DWORD WINAPI overrideFiles__internal( HANDLE readHandle )
{
    std::string first;
    std::string second;
    while ( readMapping( readHandle, first, second ) )
    {
        fileMapping.insert( std::make_pair( normalizePath( first ), second ) );
    }
    return 0;
}

extern "C" BOOL WINAPI addFileMapping( char const * virtualEntry, char const * realEntry )
{
    return fileMapping.insert( std::make_pair( normalizePath( virtualEntry ), realEntry ) ).second
        ? TRUE : FALSE;
}

extern "C" BOOL WINAPI removeFileMapping( char const * virtualEntry )
{
    FileMapping::const_iterator const iter( fileMapping.find( normalizePath( virtualEntry ) ) );
    if ( iter == fileMapping.end() )
        return FALSE;
    fileMapping.erase( iter );
    return TRUE;
}

extern "C" BOOL WINAPI clearFileMappings()
{
    fileMapping.clear();
    return TRUE;
}

BOOL WINAPI DllMain( HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved )
{
    if ( fdwReason == DLL_PROCESS_ATTACH )
        thisModule = hinstDLL;
    return TRUE;
}
