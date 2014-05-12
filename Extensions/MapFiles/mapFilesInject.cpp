#include "mapFilesInject.hpp"

#include "apiHooks.hpp"

#include <cassert>
#include <iostream>
#include <string>
#include <codecvt>
#include <locale>
#include <map>
#include <unordered_map>

#include <shlwapi.h>

typedef std::unordered_map<std::wstring, std::wstring> FileMapping;
typedef std::map<DWORD, FileMapping> FileMappings;

// Global mapping - used for current process.
FileMapping globalMapping;

// Custom mappings - used for spawning other processes.
FileMappings customMappings;

DWORD counter = 0;

HANDLE WINAPI createFileA(
  _In_      char const * lpFileName,
  _In_      DWORD dwDesiredAccess,
  _In_      DWORD dwShareMode,
  _In_opt_  LPSECURITY_ATTRIBUTES lpSecurityAttributes,
  _In_      DWORD dwCreationDisposition,
  _In_      DWORD dwFlagsAndAttributes,
  _In_opt_  HANDLE hTemplateFile
);

HANDLE WINAPI createFileW(
  _In_      wchar_t const * lpFileName,
  _In_      DWORD dwDesiredAccess,
  _In_      DWORD dwShareMode,
  _In_opt_  LPSECURITY_ATTRIBUTES lpSecurityAttributes,
  _In_      DWORD dwCreationDisposition,
  _In_      DWORD dwFlagsAndAttributes,
  _In_opt_  HANDLE hTemplateFile
);
BOOL WINAPI createProcessA(
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
);
BOOL WINAPI createProcessW(
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
);

struct MapFilesAPIHookTraits
{
    static char const moduleName[];
    static APIHookItem const items[]; 
    static unsigned int const itemsCount;
};

char const MapFilesAPIHookTraits::moduleName[] = "kernel32.dll";

APIHookItem const MapFilesAPIHookTraits::items[] = 
{
    { "CreateFileA"   , (PROC)createFileA    },
    { "CreateFileW"   , (PROC)createFileW    },
    { "CreateProcessA", (PROC)createProcessA },
    { "CreateProcessW", (PROC)createProcessW }
};

unsigned int const MapFilesAPIHookTraits::itemsCount = sizeof(items) / sizeof(items[0]);


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

HANDLE WINAPI createFileA(
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
    FileMapping::const_iterator const iter = globalMapping.find( normalizePath(
        convert.from_bytes( lpFileName ) ) );
    return CreateFileA( iter == globalMapping.end() ? lpFileName : convert.to_bytes( iter->second ).c_str(),
        dwDesiredAccess,
        dwShareMode,
        lpSecurityAttributes,
        dwCreationDisposition,
        dwFlagsAndAttributes,
        hTemplateFile
    );
}

HANDLE WINAPI createFileW(
  _In_      wchar_t const * lpFileName,
  _In_      DWORD dwDesiredAccess,
  _In_      DWORD dwShareMode,
  _In_opt_  LPSECURITY_ATTRIBUTES lpSecurityAttributes,
  _In_      DWORD dwCreationDisposition,
  _In_      DWORD dwFlagsAndAttributes,
  _In_opt_  HANDLE hTemplateFile
)
{
    FileMapping::const_iterator const iter = globalMapping.find(
        normalizePath( lpFileName ) );
    return CreateFileW
    ( 
        iter == globalMapping.end() ? lpFileName : iter->second.c_str(),
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

BOOL WINAPI createProcessA(
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
        lpProcessInformation, globalMapping );
}

BOOL WINAPI createProcessW(
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
        lpProcessInformation, globalMapping );
}

extern "C" DWORD WINAPI hookWinAPIs()
{
    return APIHooks<MapFilesAPIHookTraits>::enable();
}

extern "C" DWORD WINAPI unhookWinAPIs()
{
    return APIHooks<MapFilesAPIHookTraits>::disable();
}

extern "C" DWORD WINAPI Initialize( HANDLE readHandle )
{
    std::wstring first;
    std::wstring second;
    while ( readMapping( readHandle, first, second ) )
        globalMapping.insert( std::make_pair( normalizePath( first ), second ) );
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
    return addMapping( globalMapping, convert.from_bytes( virtualFile ),
        convert.from_bytes( file ) ) ? TRUE : FALSE;
}

extern "C" BOOL mapFileGlobalW( wchar_t const * virtualFile, wchar_t const * file )
{
    return addMapping( globalMapping, virtualFile, file ) ? TRUE : FALSE;
}

extern "C" BOOL unmapFileGlobalA( char const * virtualFile )
{
    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    return removeMapping( globalMapping, convert.from_bytes( virtualFile ) ) ? TRUE : FALSE;
}

extern "C" BOOL unmapFileGlobalW( wchar_t const * virtualFile )
{
    return removeMapping( globalMapping, virtualFile ) ? TRUE : FALSE;
}

extern "C" DWORD createFileMap()
{
    counter += 1;
    customMappings[ counter ];
    return counter;
}

extern "C" BOOL mapFileA( DWORD map, char const * virtualFile, char const * file )
{
    FileMappings::iterator const iter = customMappings.find( map );
    if ( iter == customMappings.end() )
        return FALSE;
    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    return addMapping( iter->second, convert.from_bytes( virtualFile ),
        convert.from_bytes( file ) ) ? TRUE : FALSE;
}

extern "C" BOOL mapFileW( DWORD map, wchar_t * virtualFile, wchar_t * file )
{
    FileMappings::iterator const iter = customMappings.find( map );
    if ( iter == customMappings.end() )
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
    FileMappings::iterator const iter = customMappings.find( mapping );
    if ( iter == customMappings.end() )
        return FALSE;
    BOOL const result = createProcessWithMappingWorkerA( lpApplicationName, lpCommandLine,
        lpProcessAttributes, lpThreadAttributes, bInheritHandles,
        dwCreationFlags, lpEnvironment, lpCurrentDirectory, lpStartupInfo,
        lpProcessInformation, iter->second );
    customMappings.erase( iter );
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
    FileMappings::iterator const iter = customMappings.find( mapping );
    if ( iter == customMappings.end() )
        return FALSE;
    BOOL const result = createProcessWithMappingWorkerW( lpApplicationName, lpCommandLine,
        lpProcessAttributes, lpThreadAttributes, bInheritHandles,
        dwCreationFlags, lpEnvironment, lpCurrentDirectory, lpStartupInfo,
        lpProcessInformation, iter->second );
    customMappings.erase( iter );
    return result;
}
