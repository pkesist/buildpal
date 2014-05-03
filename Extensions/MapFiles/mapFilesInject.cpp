#include "mapFilesInject.hpp"

#include "dllInject.hpp"

#include <cassert>
#include <iostream>
#include <string>
#include <codecvt>
#include <locale>
#include <map>
#include <unordered_map>

#include <psapi.h>
#include <shlwapi.h>

typedef std::unordered_map<std::wstring, std::wstring> FileMapping;
typedef std::map<DWORD, FileMapping> FileMappings;

FileMapping fileMapping;
HMODULE thisModule;

FileMappings fileMappings;
DWORD counter = 0;

namespace
{
    bool readMapping( HANDLE readHandle, std::wstring & f, std::wstring & s )
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
        std::wstring first;
        first.resize( firstSize );
        success = ReadFile( readHandle, &first[0], firstSize * sizeof(std::wstring::value_type), &read, 0 );
        assert( success );
        assert( read == firstSize * sizeof(std::wstring::value_type) );
        std::wstring second;
        second.resize( secondSize );
        success = ReadFile( readHandle, &second[0], secondSize * sizeof(std::wstring::value_type), &read, 0 );
        assert( success );
        assert( read == secondSize * sizeof(std::wstring::value_type) );
        f.swap( first );
        s.swap( second );
        return true;
    }

    void writeMapping( HANDLE writeHandle, std::wstring const & first, std::wstring const & second )
    {
        assert( first.size() < 0xFFFF );
        assert( second.size() < 0xFFFF );
        unsigned char sizes[4];
        sizes[0] = first.size() & 0xFF;
        sizes[1] = first.size() >> 8;
        sizes[2] = second.size() & 0xFF;
        sizes[3] = second.size() >> 8;
        DWORD written;
        BOOL result;
        result = WriteFile( writeHandle, sizes, 4, &written, 0 );
        assert( result );
        assert( written == 4 );
        result = WriteFile( writeHandle, first.data(), first.size() * sizeof(std::wstring::value_type), &written, 0 );
        assert( result );
        assert( written == first.size() * sizeof(std::wstring::value_type) );
        result = WriteFile( writeHandle, second.data(), second.size() * sizeof(std::wstring::value_type), &written, 0 );
        assert( result );
        assert( written == second.size() * sizeof(std::wstring::value_type) );
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

    bool hookProcess( HANDLE processHandle, FileMapping const & fileMapping )
    {
        HANDLE pipeRead;
        HANDLE pipeWrite;
        BOOL result;
        result = CreatePipe( &pipeRead, &pipeWrite, 0, 0 );
        assert( result );
        HANDLE targetRead;
        result = DuplicateHandle( GetCurrentProcess(), pipeRead,
            processHandle, &targetRead, 0, FALSE,
            DUPLICATE_SAME_ACCESS | DUPLICATE_CLOSE_SOURCE );
        assert( result );

        FileMapping::const_iterator end = fileMapping.end();
        for ( FileMapping::const_iterator iter = fileMapping.begin(); iter != end; ++iter )
            writeMapping( pipeWrite, iter->first, iter->second );
        writeEnd( pipeWrite );

        char const * dllNames[] = {
            "map_files_inj32.dll",
            "map_files_inj64.dll"
        };
        char const initFunc[] = "Initialize";
        return injectLibrary( processHandle, dllNames, initFunc, targetRead );
    }

    std::wstring normalizePath( std::wstring path )
    {
        std::wstring::iterator const end = path.end();
        for ( std::wstring::iterator iter = path.begin(); iter != end; ++iter )
            if ( *iter == L'/' )
                *iter = L'\\';
        wchar_t buffer[MAX_PATH];
        BOOL result = PathCanonicalizeW( buffer, path.c_str() );
        assert( result );
        return CharLowerW( buffer );
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
    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    FileMapping::const_iterator const iter = fileMapping.find( normalizePath(
        convert.from_bytes( lpFileName ) ) );
    return CreateFileA( iter == fileMapping.end() ? lpFileName : convert.to_bytes( iter->second ).c_str(),
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
    FileMapping::const_iterator const iter = fileMapping.find(
        normalizePath( lpFileName ) );
    return CreateFileW
    ( 
        iter == fileMapping.end() ? lpFileName : iter->second.c_str(),
        dwDesiredAccess,
        dwShareMode,
        lpSecurityAttributes,
        dwCreationDisposition,
        dwFlagsAndAttributes,
        hTemplateFile
    );
}

namespace
{
    BOOL createProcessWithMappingWorkerA(
        char const * lpApplicationName,
        char * lpCommandLine,
        LPSECURITY_ATTRIBUTES lpProcessAttributes,
        LPSECURITY_ATTRIBUTES lpThreadAttributes,
        BOOL bInheritHandles,
        DWORD dwCreationFlags,
        LPVOID lpEnvironment,
        char const * lpCurrentDirectory,
        LPSTARTUPINFOA lpStartupInfo,
        LPPROCESS_INFORMATION lpProcessInformation,
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
            hookProcess( lpProcessInformation->hProcess, fileMapping );
            if ( shouldResume )
                ResumeThread( lpProcessInformation->hThread );
        }
        return result;
    }

    BOOL createProcessWithMappingWorkerW(
        wchar_t const * lpApplicationName,
        wchar_t * lpCommandLine,
        LPSECURITY_ATTRIBUTES lpProcessAttributes,
        LPSECURITY_ATTRIBUTES lpThreadAttributes,
        BOOL bInheritHandles,
        DWORD dwCreationFlags,
        LPVOID lpEnvironment,
        wchar_t const * lpCurrentDirectory,
        LPSTARTUPINFOW lpStartupInfo,
        LPPROCESS_INFORMATION lpProcessInformation,
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
            hookProcess( lpProcessInformation->hProcess, fileMapping );
            if ( shouldResume )
                ResumeThread( lpProcessInformation->hThread );
        }
        return result;
    }
}

BOOL createProcessWithGlobalMappingA(
    _In_opt_     char const * lpApplicationName,
    _Inout_opt_  char * lpCommandLine,
    _In_opt_     LPSECURITY_ATTRIBUTES lpProcessAttributes,
    _In_opt_     LPSECURITY_ATTRIBUTES lpThreadAttributes,
    _In_         BOOL bInheritHandles,
    _In_         DWORD dwCreationFlags,
    _In_opt_     LPVOID lpEnvironment,
    _In_opt_     char const * lpCurrentDirectory,
    _In_         LPSTARTUPINFOA lpStartupInfo,
    _Out_        LPPROCESS_INFORMATION lpProcessInformation
)
{
    return createProcessWithMappingWorkerA( lpApplicationName, lpCommandLine,
        lpProcessAttributes, lpThreadAttributes, bInheritHandles,
        dwCreationFlags, lpEnvironment, lpCurrentDirectory, lpStartupInfo,
        lpProcessInformation, fileMapping );
}

BOOL createProcessWithGlobalMappingW(
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
    return createProcessWithMappingWorkerW( lpApplicationName, lpCommandLine,
        lpProcessAttributes, lpThreadAttributes, bInheritHandles,
        dwCreationFlags, lpEnvironment, lpCurrentDirectory, lpStartupInfo,
        lpProcessInformation, fileMapping );
}

HMODULE WINAPI hookLoadLibraryA( char * lpFileName )
{
    HMODULE result = ::LoadLibraryA( lpFileName );
    hookWinAPIs();
    return result;
}

HMODULE WINAPI hookLoadLibraryW( wchar_t * lpFileName )
{
    HMODULE result = ::LoadLibraryW( lpFileName );
    hookWinAPIs();
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

extern "C" DWORD WINAPI hookWinAPIs()
{
    hookWinAPI( "Kernel32.dll", "CreateFileA", (PROC)hookCreateFileA );
    hookWinAPI( "Kernel32.dll", "CreateFileW", (PROC)hookCreateFileW );
    hookWinAPI( "Kernel32.dll", "LoadLibraryA", (PROC)hookLoadLibraryA );
    hookWinAPI( "Kernel32.dll", "LoadLibraryW", (PROC)hookLoadLibraryW );
    hookWinAPI( "Kernel32.dll", "CreateProcessA", (PROC)createProcessWithGlobalMappingA );
    hookWinAPI( "Kernel32.dll", "CreateProcessW", (PROC)createProcessWithGlobalMappingW );
    return 0;
}

extern "C" DWORD WINAPI unhookWinAPIs()
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

extern "C" DWORD WINAPI Initialize( HANDLE readHandle )
{
    std::wstring first;
    std::wstring second;
    while ( readMapping( readHandle, first, second ) )
        fileMapping.insert( std::make_pair( normalizePath( first ), second ) );
    hookWinAPIs();
    return 0;
}

namespace
{
    bool addMapping( FileMapping & fileMapping, std::wstring const & virtualFile, std::wstring const & file )
    {
        fileMapping[ normalizePath( virtualFile ) ] = file;
        return true;
    }

    bool removeMapping( FileMapping & fileMapping, std::wstring const & virtualFile )
    {
        return fileMapping.erase( normalizePath( virtualFile ) ) == 1;
    }
}

extern "C" BOOL mapFileGlobalA( char const * virtualFile, char const * file )
{
    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    return addMapping( fileMapping, convert.from_bytes( virtualFile ),
        convert.from_bytes( file ) ) ? TRUE : FALSE;
}

extern "C" BOOL mapFileGlobalW( wchar_t const * virtualFile, wchar_t const * file )
{
    return addMapping( fileMapping, virtualFile, file ) ? TRUE : FALSE;
}

extern "C" BOOL unmapFileGlobalA( char const * virtualFile )
{
    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    return removeMapping( fileMapping, convert.from_bytes( virtualFile ) ) ? TRUE : FALSE;
}

extern "C" BOOL unmapFileGlobalW( wchar_t const * virtualFile )
{
    return removeMapping( fileMapping, virtualFile ) ? TRUE : FALSE;
}

extern "C" DWORD createFileMap()
{
    counter += 1;
    fileMappings[ counter ];
    return counter;
}

extern "C" BOOL mapFileA( DWORD map, char const * virtualFile, char const * file )
{
    FileMappings::iterator const iter = fileMappings.find( map );
    if ( iter == fileMappings.end() )
        return FALSE;
    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    return addMapping( iter->second, convert.from_bytes( virtualFile ),
        convert.from_bytes( file ) ) ? TRUE : FALSE;
}

extern "C" BOOL mapFileW( DWORD map, wchar_t * virtualFile, wchar_t * file )
{
    FileMappings::iterator const iter = fileMappings.find( map );
    if ( iter == fileMappings.end() )
        return FALSE;
    return addMapping( iter->second, virtualFile, file ) ? TRUE : FALSE;
}

extern "C" BOOL WINAPI createProcessWithMappingA(
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
    _In_         DWORD mapping
)
{
    FileMappings::iterator const iter = fileMappings.find( mapping );
    if ( iter == fileMappings.end() )
        return FALSE;
    BOOL const result = createProcessWithMappingWorkerA( lpApplicationName, lpCommandLine,
        lpProcessAttributes, lpThreadAttributes, bInheritHandles,
        dwCreationFlags, lpEnvironment, lpCurrentDirectory, lpStartupInfo,
        lpProcessInformation, iter->second );
    fileMappings.erase( iter );
    return result;
}

extern "C" BOOL WINAPI createProcessWithMappingW(
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
    _In_         DWORD mapping
)
{
    FileMappings::iterator const iter = fileMappings.find( mapping );
    if ( iter == fileMappings.end() )
        return FALSE;
    BOOL const result = createProcessWithMappingWorkerW( lpApplicationName, lpCommandLine,
        lpProcessAttributes, lpThreadAttributes, bInheritHandles,
        dwCreationFlags, lpEnvironment, lpCurrentDirectory, lpStartupInfo,
        lpProcessInformation, iter->second );
    fileMappings.erase( iter );
    return result;
}

BOOL WINAPI DllMain( HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved )
{
    if ( fdwReason == DLL_PROCESS_ATTACH )
    {
        thisModule = hinstDLL;
    }
    return TRUE;
}
