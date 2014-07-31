#include "mapFiles.hpp"

#include "..\Common\apiHooks.hpp"
#include "..\Common\createProcessMacros.hpp"

#include <cassert>
#include <iostream>
#include <string>
#include <codecvt>
#include <locale>
#include <map>
#include <set>
#include <unordered_map>

#include <winternl.h>
#include <shlwapi.h>

#pragma comment( lib, "ntdll.lib" )

struct FileMapping
{
    typedef std::map<std::wstring, std::wstring> FileList;
    typedef std::unordered_map<std::wstring, FileList> DirMap;

    void addFile( std::wstring const & virtualAbsPath, std::wstring const & realFile )
    {
        std::pair<std::wstring, std::wstring> dirAndFile( decomposePath( virtualAbsPath ) );
        addFile( dirAndFile.first, dirAndFile.second, realFile );
    }

    void addFile( std::wstring const & virtualDir, std::wstring const & virtualFile, std::wstring const & realFile )
    {
        dirMap_[ virtualDir ][ virtualFile ] = realFile;
    }

    void removeFile( std::wstring const & virtualAbsPath )
    {
        std::pair<std::wstring, std::wstring> dirAndFile( decomposePath( virtualAbsPath ) );
        dirMap_[ dirAndFile.first ].erase( dirAndFile.second );
    }

    std::wstring const * realFile( std::wstring const & virtualFile ) const
    {
        std::pair<std::wstring, std::wstring> dirAndFile( decomposePath( virtualFile ) );
        DirMap::const_iterator iter( dirMap_.find( dirAndFile.first ) );
        if ( iter == dirMap_.end() )
            return 0;
        FileList::const_iterator fileIter( iter->second.find( dirAndFile.second ) );
        if ( fileIter == iter->second.end() )
            return 0;
        return &fileIter->second;
    }

    DirMap const & getDirs() const { return dirMap_; }

protected:
    static std::wstring normalizePath( std::wstring path )
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

    static std::pair<std::wstring, std::wstring> decomposePath( std::wstring const & path )
    {
        std::wstring normalizedPath( normalizePath( path ) );
        wchar_t const * str( normalizedPath.c_str() );
        wchar_t const * file( PathFindFileNameW( str ) );
        unsigned int offset( file - str );
        return std::make_pair( normalizedPath.substr( 0, offset ), normalizedPath.substr( offset ) ); 
    }

private:
    DirMap dirMap_;
};

class GlobalFileMapping : public FileMapping
{
public:
    bool getDir( std::wstring const & path, HANDLE & h ) const
    {
        std::wstring normalizedPath( normalizePath( path ) );
        if ( normalizedPath[ normalizedPath.size() - 1 ] != L'\\' )
            normalizedPath.push_back( L'\\' );
        DirMap::const_iterator const iter( getDirs().find( normalizedPath ) );
        if ( iter == getDirs().end() )
            return false;
        h = fakeHandle_;
        return true;
    }

    bool isFake( HANDLE handle ) const
    {
        return handle == fakeHandle_;
    }

private:
    static HANDLE fakeHandle_;
};

HANDLE GlobalFileMapping::fakeHandle_ = reinterpret_cast<HANDLE>( 0xFAB0BEEF );

typedef std::map<DWORD, FileMapping> FileMappings;

decltype(CreateProcessA) createProcessA;
decltype(CreateProcessW) createProcessW;
decltype(GetFileAttributesA) getFileAttributesA;
decltype(GetFileAttributesW) getFileAttributesW;
decltype(GetFileAttributesExA) getFileAttributesExA;
decltype(GetFileAttributesExW) getFileAttributesExW;
decltype(NtCreateFile) ntCreateFile;
decltype(NtClose) ntClose;

NTSTATUS NTAPI ntQueryDirectoryFile(
  _In_      HANDLE fileHandle,
  _In_opt_  HANDLE event,
  _In_opt_  PVOID apcRoutine,
  _In_opt_  PVOID apcContext,
  _Out_     PVOID ioStatusBlock,
  _Out_     PVOID fileInformation,
  _In_      ULONG length,
  _In_      int fileInformationClass,
  _In_      BOOLEAN returnSingleEntry,
  _In_opt_  PUNICODE_STRING fileName,
  _In_      BOOLEAN restartScan
);

struct Kernel32ApiHookDesc
{
    static char const moduleName[];
    static APIHookItem const items[]; 
    static unsigned int const itemsCount;
};

char const Kernel32ApiHookDesc::moduleName[] = "kernel32.dll";

APIHookItem const Kernel32ApiHookDesc::items[] = 
{
    { "CreateProcessA", (PROC)createProcessA },
    { "CreateProcessW", (PROC)createProcessW },
    { "GetFileAttributesA", (PROC)getFileAttributesA },
    { "GetFileAttributesW", (PROC)getFileAttributesW },
    { "GetFileAttributesExA", (PROC)getFileAttributesExA },
    { "GetFileAttributesExW", (PROC)getFileAttributesExW }
};

unsigned int const Kernel32ApiHookDesc::itemsCount = sizeof(items) / sizeof(items[0]);

struct NtDllHookDesc
{
    static char const moduleName[];
    static APIHookItem const items[]; 
    static unsigned int const itemsCount;
};

char const NtDllHookDesc::moduleName[] = "ntdll.dll";

APIHookItem const NtDllHookDesc::items[] = 
{
    { "NtClose", (PROC)ntClose },
    { "NtCreateFile", (PROC)ntCreateFile },
    { "NtQueryDirectoryFile", (PROC)ntQueryDirectoryFile }
};

unsigned int const NtDllHookDesc::itemsCount = sizeof(items) / sizeof(items[0]);

struct MapFilesAPIHookData
{
    // Global mapping - used for current process.
    GlobalFileMapping globalMapping;

    // Custom mappings - used for spawning other processes.
    FileMappings customMappings;

    unsigned int counter;
};

decltype(&createProcessA) origCreateProcessA;
decltype(&createProcessW) origCreateProcessW;
decltype(&getFileAttributesA) origGetFileAttributesA;
decltype(&getFileAttributesW) origGetFileAttributesW;
decltype(&getFileAttributesExA) origGetFileAttributesExA;
decltype(&getFileAttributesExW) origGetFileAttributesExW;
decltype(&ntClose) origNtClose;
decltype(&ntCreateFile) origNtCreateFile;
decltype(&ntQueryDirectoryFile) origNtQueryDirectoryFile;

struct MapFilesAPIHook : APIHooks<MapFilesAPIHook, MapFilesAPIHookData>
{
    template <typename FuncType>
    FuncType getOriginal( FuncType func )
    {
        return reinterpret_cast<FuncType>( originalProc(
            reinterpret_cast<PROC>( func ) ) );
    }

    MapFilesAPIHook()
    {
        addAPIHook<Kernel32ApiHookDesc>();
        addAPIHook<NtDllHookDesc>();

        origCreateProcessA       = getOriginal( &createProcessA       );
        origCreateProcessW       = getOriginal( &createProcessW       );
        origGetFileAttributesA   = getOriginal( &getFileAttributesA   );
        origGetFileAttributesW   = getOriginal( &getFileAttributesW   );
        origGetFileAttributesExA = getOriginal( &getFileAttributesExA );
        origGetFileAttributesExW = getOriginal( &getFileAttributesExW );
        origNtClose              = getOriginal( &ntClose              );
        origNtCreateFile         = getOriginal( &ntCreateFile         );
        origNtQueryDirectoryFile = getOriginal( &ntQueryDirectoryFile );
    }
};

namespace
{
    bool readDir( HANDLE readHandle, std::wstring & dirName, std::size_t & entriesCount )
    {
        BOOL success;
        DWORD read;
        unsigned char entriesBuffer[4];
        success = ReadFile( readHandle, entriesBuffer, 4, &read, 0 );
        if ( !success )
            return false;
        assert( read == 4 );
        std::size_t const entries = ( entriesBuffer[3] << 24 ) | ( entriesBuffer[2] << 16 ) | ( entriesBuffer[1] << 8 ) | entriesBuffer[0];
        if ( entries )
        {
            unsigned char sizeBuff[2];
            success = ReadFile( readHandle, sizeBuff, 2, &read, 0 );
            if ( !success )
                return false;
            assert( read == 2 );
            std::size_t const size = ( sizeBuff[1] << 8 ) + sizeBuff[0];
            std::wstring str;
            str.resize( size );
            success = ReadFile( readHandle, &str[0], size * sizeof(wchar_t), &read, 0 );
            if ( !success )
                return false;
            assert( size * sizeof(wchar_t) );
            dirName.swap( str );
        }
        entriesCount = entries;
        return true;
    }

    bool readMapping( HANDLE readHandle, std::wstring & f, std::wstring & s )
    {
        BOOL success;
        DWORD read;
        unsigned char sizes[4];
        success = ReadFile( readHandle, sizes, 4, &read, 0 );
        if ( !success )
            return false;
        assert( read == 4 );
        std::size_t const firstSize = ( sizes[1] << 8 ) + sizes[0];
        std::size_t const secondSize = ( sizes[3] << 8 ) + sizes[2];
        std::wstring first;
        first.resize( firstSize );
        success = ReadFile( readHandle, &first[0], firstSize * sizeof(wchar_t), &read, 0 );
        if ( !success )
            return false;
        assert( read == firstSize * sizeof(std::wstring::value_type) );
        std::wstring second;
        second.resize( secondSize );
        success = ReadFile( readHandle, &second[0], secondSize * sizeof(wchar_t), &read, 0 );
        if ( !success )
            return false;
        assert( read == secondSize * sizeof(wchar_t) );
        f.swap( first );
        s.swap( second );
        return true;
    }

    bool writeDir( HANDLE writeHandle, std::wstring const & dirName, std::size_t entries )
    {
        DWORD written;
        BOOL result;

        unsigned char entriesBuffer[4];
        entriesBuffer[0] = entries & 0xFF;
        entriesBuffer[1] = ( entries >> 8 ) & 0xFF;
        entriesBuffer[2] = ( entries >> 16 ) & 0xFF;
        entriesBuffer[3] = ( entries >> 24 ) & 0xFF;
        result = WriteFile( writeHandle, entriesBuffer, 4, &written, 0 );
        if ( !result )
            return false;
        assert( written == 4 );

        assert( dirName.size() < 0xFFFF );
        unsigned char sizeBuffer[2];
        sizeBuffer[0] = dirName.size() & 0xFF;
        sizeBuffer[1] = dirName.size() >> 8;
        result = WriteFile( writeHandle, sizeBuffer, 2, &written, 0 );
        if ( !result )
            return false;
        assert( written == 2 );

        result = WriteFile( writeHandle, dirName.c_str(), dirName.size() * sizeof(wchar_t), &written, 0 );
        if ( !result )
            return false;
        assert( written == dirName.size() * sizeof(wchar_t) );
        return true;
    }

    bool writeMapping( HANDLE writeHandle, std::wstring const & first, std::wstring const & second )
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
        if ( !result )
            return false;
        assert( written == 4 );
        result = WriteFile( writeHandle, first.data(), first.size() * sizeof(wchar_t), &written, 0 );
        if ( !result )
            return false;
        assert( written == first.size() * sizeof(std::wstring::value_type) );
        result = WriteFile( writeHandle, second.data(), second.size() * sizeof(wchar_t), &written, 0 );
        if ( !result )
            return false;
        assert( written == second.size() * sizeof(wchar_t) );
        return true;
    };

    bool writeEnd( HANDLE writeHandle )
    {
        char end[4] = { 0 };
        DWORD written;
        BOOL result;
        result = WriteFile( writeHandle, end, 4, &written, 0 );
        assert( !result || ( written == 4 ) );
        return result != 0;
    }

    struct InitArgs
    {
        FileMapping const * const * mappings;
        DWORD mappingCount;
        HANDLE writeHandle;
    };

    DWORD writeMappings( void * vpInitArgs )
    {
        InitArgs const * initArgs( static_cast<InitArgs *>( vpInitArgs ) );
        
        for ( DWORD mappingIndex( 0 ); mappingIndex < initArgs->mappingCount; ++mappingIndex )
        {
            FileMapping const & fileMap = (*initArgs->mappings[ mappingIndex ]);
            for ( FileMapping::DirMap::value_type const & dirEntry : fileMap.getDirs() )
            {
                if ( !writeDir( initArgs->writeHandle, dirEntry.first, dirEntry.second.size() ) )
                    return (DWORD)-1;
                for ( FileMapping::FileList::value_type const & fileEntry : dirEntry.second )
                    if ( !writeMapping( initArgs->writeHandle, fileEntry.first, fileEntry.second ) )
                        return (DWORD)-1;
            }
        }
        return writeEnd( initArgs->writeHandle ) ? 0 : (DWORD)-1;

    }

    bool hookProcess( HANDLE processHandle, FileMapping const * const * fileMapping, DWORD fileMappingCount )
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

        char const * dllNames[] = {
            "map_files_inj32.dll",
            "map_files_inj64.dll"
        };
        char const initFunc[] = "Initialize";
        InitArgs writeMappingsArgs =
        {
            fileMapping,
            fileMappingCount,
            pipeWrite
        };
        return injectLibrary( processHandle, dllNames,
            initFunc, targetRead, writeMappings, &writeMappingsArgs  );
    }
}

NTSTATUS NTAPI ntCreateFile(
  _Out_     PHANDLE fileHandle,
  _In_      ACCESS_MASK desiredAccess,
  _In_      POBJECT_ATTRIBUTES objectAttributes,
  _Out_     PIO_STATUS_BLOCK ioStatusBlock,
  _In_opt_  PLARGE_INTEGER allocationSize,
  _In_      ULONG fileAttributes,
  _In_      ULONG shareAccess,
  _In_      ULONG createDisposition,
  _In_      ULONG createOptions,
  _In_      PVOID eaBuffer,
  _In_      ULONG eaLength
)
{
    if ( objectAttributes )
    {
        PUNICODE_STRING str = objectAttributes->ObjectName;
        if
        (
            ( str->Length > 4 ) && ( str->Buffer[0] == '\\' ) &&
            ( str->Buffer[1] == '?' ) && ( str->Buffer[2] == '?' ) &&
            ( str->Buffer[3] == '\\' )
        )
        {
            std::wstring const searchFor( str->Buffer + 4, ( str->Length / sizeof(wchar_t) ) - 4 );
            MapFilesAPIHook::Data & data( MapFilesAPIHook::getData() );
            
            if ( data.globalMapping.getDir( searchFor, *fileHandle ) )
            {
                ioStatusBlock->Information = FILE_EXISTS;
                return 0;
            }

            std::wstring const * realFile( data.globalMapping.realFile( searchFor ) );
            if ( realFile )
            {
                std::size_t const size( realFile->size() + 4 + 1 );
                wchar_t * buffer = (wchar_t *)alloca( size * sizeof(wchar_t) );
                buffer[0] = L'\\';
                buffer[1] = L'?';
                buffer[2] = L'?';
                buffer[3] = L'\\';
                std::memcpy( buffer + 4, realFile->c_str(), ( size - 4 ) * sizeof(wchar_t) );
                UNICODE_STRING uc;
                uc.Buffer = buffer;
                uc.MaximumLength = size * sizeof(wchar_t);
                uc.Length = ( size - 1 ) * sizeof(wchar_t);
                PUNICODE_STRING old = objectAttributes->ObjectName;
                objectAttributes->ObjectName = &uc;
                NTSTATUS result = origNtCreateFile( fileHandle, desiredAccess, objectAttributes,
                    ioStatusBlock, allocationSize, fileAttributes, shareAccess,
                    createDisposition, createOptions, eaBuffer, eaLength );
                objectAttributes->ObjectName = str;
                return result;
            }
        }
    }
    return origNtCreateFile( fileHandle, desiredAccess, objectAttributes,
        ioStatusBlock, allocationSize, fileAttributes, shareAccess,
        createDisposition, createOptions, eaBuffer, eaLength );
}

NTSTATUS NTAPI ntQueryDirectoryFile(
  _In_      HANDLE fileHandle,
  _In_opt_  HANDLE event,
  _In_opt_  PVOID apcRoutine,
  _In_opt_  PVOID apcContext,
  _Out_     PVOID ioStatusBlock,
  _Out_     PVOID fileInformation,
  _In_      ULONG length,
  _In_      int fileInformationClass,
  _In_      BOOLEAN returnSingleEntry,
  _In_opt_  PUNICODE_STRING fileName,
  _In_      BOOLEAN restartScan
)
{
    if ( MapFilesAPIHook::getData().globalMapping.isFake( fileHandle ) )
    {
        // Compiler is trying to query our virtual directory.
        // Everybody look busy!
        return ((NTSTATUS)0x80000011L); // STATUS_DEVICE_BUSY
    }
    NTSTATUS result = origNtQueryDirectoryFile( fileHandle, event, apcRoutine, apcContext, ioStatusBlock,
        fileInformation, length, fileInformationClass, returnSingleEntry,
        fileName, restartScan );
    return result;
}

NTSTATUS WINAPI ntClose(
  _In_  HANDLE handle
)
{
    if ( MapFilesAPIHook::getData().globalMapping.isFake( handle ) )
        return 0;
    return origNtClose( handle );
}

DWORD WINAPI getFileAttributesA( char const * lpFileName )
{
    MapFilesAPIHook::Data & data( MapFilesAPIHook::getData() );
    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    std::wstring const * realFile( data.globalMapping.realFile(
        convert.from_bytes( lpFileName ) ) );
    if ( realFile )
        return origGetFileAttributesW( realFile->c_str() );
    return origGetFileAttributesA( lpFileName );
}

DWORD WINAPI getFileAttributesW( wchar_t const * lpFileName )
{
    MapFilesAPIHook::Data & data( MapFilesAPIHook::getData() );
    std::wstring const * realFile( data.globalMapping.realFile(
        lpFileName ) );
    if ( realFile )
        return origGetFileAttributesW( realFile->c_str() );
    return origGetFileAttributesW( lpFileName );
}

BOOL WINAPI getFileAttributesExA(
  _In_   char const * lpFileName,
  _In_   GET_FILEEX_INFO_LEVELS fInfoLevelId,
  _Out_  LPVOID lpFileInformation
)
{
    MapFilesAPIHook::Data & data( MapFilesAPIHook::getData() );
    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    std::wstring const * realFile( data.globalMapping.realFile(
        convert.from_bytes( lpFileName ) ) );
    if ( realFile )
        return origGetFileAttributesExW( realFile->c_str(), fInfoLevelId, lpFileInformation );
    return origGetFileAttributesExA( lpFileName, fInfoLevelId, lpFileInformation );
}
BOOL WINAPI getFileAttributesExW(
  _In_   wchar_t const * lpFileName,
  _In_   GET_FILEEX_INFO_LEVELS fInfoLevelId,
  _Out_  LPVOID lpFileInformation
)
{
    MapFilesAPIHook::Data & data( MapFilesAPIHook::getData() );
    std::wstring const * realFile( data.globalMapping.realFile(
        lpFileName ) );
    if ( realFile )
        return origGetFileAttributesExW( realFile->c_str(), fInfoLevelId, lpFileInformation );
    return origGetFileAttributesExW( lpFileName, fInfoLevelId, lpFileInformation );
}

namespace
{
    BOOL createProcessWithMappingWorkerA(
        CREATE_PROCESS_PARAMSA,
        FileMapping const * const * fileMapping,
        DWORD fileMappingCount
    )
    {
        bool const shouldResume = (dwCreationFlags & CREATE_SUSPENDED) == 0;
        BOOL result = origCreateProcessA( lpApplicationName, lpCommandLine,
            lpProcessAttributes, lpThreadAttributes,bInheritHandles,
            dwCreationFlags | CREATE_SUSPENDED,lpEnvironment,lpCurrentDirectory,
            lpStartupInfo, lpProcessInformation);
        if ( result )
        {
            hookProcess( lpProcessInformation->hProcess, fileMapping,
                fileMappingCount );
            if ( shouldResume )
                ResumeThread( lpProcessInformation->hThread );
        }
        return result;
    }

    BOOL createProcessWithMappingWorkerW(
        CREATE_PROCESS_PARAMSW,
        FileMapping const * const * fileMapping,
        DWORD fileMappingCount
    )
    {
        bool const shouldResume = (dwCreationFlags & CREATE_SUSPENDED) == 0;
        BOOL result = origCreateProcessW( lpApplicationName, lpCommandLine,
            lpProcessAttributes, lpThreadAttributes,bInheritHandles,
            dwCreationFlags | CREATE_SUSPENDED,lpEnvironment,lpCurrentDirectory,
            lpStartupInfo, lpProcessInformation);
        if ( result )
        {
            hookProcess( lpProcessInformation->hProcess, fileMapping,
                fileMappingCount );
            if ( shouldResume )
                ResumeThread( lpProcessInformation->hThread );
        }
        return result;
    }
}

BOOL WINAPI createProcessA( CREATE_PROCESS_PARAMSA )
{
    FileMapping const * const mapping = &MapFilesAPIHook::getData().globalMapping;
    return createProcessWithMappingWorkerA( CREATE_PROCESS_ARGS, &mapping, 1 );
}

BOOL WINAPI createProcessW( CREATE_PROCESS_PARAMSW )
{
    FileMapping const * const mapping = &MapFilesAPIHook::getData().globalMapping;
    return createProcessWithMappingWorkerW( CREATE_PROCESS_ARGS, &mapping, 1 );
}

DWORD WINAPI hookWinAPIs()
{
    return MapFilesAPIHook::enable();
}

DWORD WINAPI unhookWinAPIs()
{
    return MapFilesAPIHook::disable();
}

DWORD WINAPI Initialize( HANDLE readHandle )
{
    std::wstring dirName;
    std::size_t numEntries;
    for ( ; ; )
    {
        if ( !readDir( readHandle, dirName, numEntries ) )
            return (DWORD)-1;

        if ( numEntries == 0 )
            break;

        for ( std::size_t entry( 0 ); entry < numEntries; ++entry )
        {
            std::wstring fileName;
            std::wstring realFile;
            if ( !readMapping( readHandle, fileName, realFile ) )
                return (DWORD)-2;
            MapFilesAPIHook::getData().globalMapping.addFile( dirName, fileName, realFile );
        }
    }
    hookWinAPIs();
    return 0;
}

BOOL mapFileGlobalA( char const * virtualFile, char const * file )
{
    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    MapFilesAPIHook::getData().globalMapping.addFile(
        convert.from_bytes( virtualFile ),
        convert.from_bytes( file ) );
    return TRUE;
}

BOOL mapFileGlobalW( wchar_t const * virtualFile, wchar_t const * file )
{
    MapFilesAPIHook::getData().globalMapping.addFile( virtualFile, file );
    return TRUE;
}

BOOL unmapFileGlobalA( char const * virtualFile )
{
    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    MapFilesAPIHook::getData().globalMapping.removeFile(
        convert.from_bytes( virtualFile ) );
    return TRUE;
}

BOOL unmapFileGlobalW( wchar_t const * virtualFile )
{
    MapFilesAPIHook::getData().globalMapping.removeFile( virtualFile );
    return TRUE;
}

DWORD createFileMap()
{
    MapFilesAPIHook::Data & data( MapFilesAPIHook::getData() );
    data.counter += 1;
    data.customMappings[ data.counter ];
    return data.counter;
}

void destroyFileMap( DWORD id )
{
    MapFilesAPIHook::getData().customMappings.erase( id );
}

BOOL mapFileA( DWORD map, char const * virtualFile, char const * file )
{
    MapFilesAPIHook::Data & data( MapFilesAPIHook::getData() );
    FileMappings::iterator const iter = data.customMappings.find( map );
    if ( iter == data.customMappings.end() )
        return FALSE;
    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    iter->second.addFile( convert.from_bytes( virtualFile ),
        convert.from_bytes( file ) );
    return TRUE;
}

BOOL mapFileW( DWORD map, wchar_t * virtualFile, wchar_t * file )
{
    MapFilesAPIHook::Data & data( MapFilesAPIHook::getData() );
    FileMappings::iterator const iter = data.customMappings.find( map );
    if ( iter == data.customMappings.end() )
        return FALSE;
    iter->second.addFile( virtualFile, file );
    return TRUE;
}

BOOL WINAPI createProcessWithMappingA(
    CREATE_PROCESS_PARAMSA,
    DWORD const * mappings,
    DWORD mappingsCount
)
{
    MapFilesAPIHook::Data & data( MapFilesAPIHook::getData() );
    std::vector<FileMapping const *> vec( mappingsCount );
    for ( DWORD index( 0 ); index < mappingsCount; ++index )
    {
        FileMappings::iterator const iter = data.customMappings.find( mappings[ index ] );
        if ( iter == data.customMappings.end() )
            return FALSE;
        vec[ index ] = &iter->second;
    }
    BOOL const result = createProcessWithMappingWorkerA( CREATE_PROCESS_ARGS,
        vec.data(), vec.size() );
    return result;
}

BOOL WINAPI createProcessWithMappingW(
    CREATE_PROCESS_PARAMSW,
    DWORD const * mappings,
    DWORD mappingsCount
)
{
    MapFilesAPIHook::Data & data( MapFilesAPIHook::getData() );
    std::vector<FileMapping const *> vec( mappingsCount );
    for ( DWORD index( 0 ); index < mappingsCount; ++index )
    {
        FileMappings::iterator const iter = data.customMappings.find( mappings[ index ] );
        if ( iter == data.customMappings.end() )
            return FALSE;
        vec[ index ] = &iter->second;
    }
    BOOL const result = createProcessWithMappingWorkerW( CREATE_PROCESS_ARGS,
        vec.data(), vec.size() );
    return result;
}
