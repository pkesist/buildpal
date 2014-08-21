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
        addFile( dirAndFile.first, dirAndFile.second, L"\\??\\" + realFile );
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

    bool realFile( wchar_t const * virtualFile, std::size_t len, PUNICODE_STRING str )
    {
        return realFile( std::wstring( virtualFile, len ), str );
    }

    bool realFile( std::wstring const & virtualFile, PUNICODE_STRING str )
    {
        std::pair<std::wstring, std::wstring> dirAndFile( decomposePath( virtualFile ) );
        DirMap::iterator iter( dirMap_.find( dirAndFile.first ) );
        if ( iter == dirMap_.end() )
            return false;
        FileList::iterator fileIter( iter->second.find( dirAndFile.second ) );
        if ( fileIter == iter->second.end() )
            return false;
        str->Buffer = &fileIter->second[0];
        str->Length = str->MaximumLength = fileIter->second.size() * sizeof(wchar_t);
        return true;
    }

    DirMap const & getDirs() const { return dirMap_; }

protected:
    static std::wstring normalizePath( std::wstring path )
    {
        std::wstring::iterator const end = path.end();
        for ( std::wstring::iterator iter = path.begin(); iter != end; ++iter )
        {
            if ( *iter == L'/' )
                *iter = L'\\';
            else
                *iter = (wchar_t)CharLowerW( (wchar_t *)*iter );
        }
        wchar_t buffer[MAX_PATH];
        BOOL result = PathCanonicalizeW( buffer, path.c_str() );
        return buffer;
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
    bool getDir( wchar_t const * virtualFile, std::size_t len, HANDLE & h )
    {
        return getDir( std::wstring( virtualFile, len ), h );
    }

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

typedef struct _FILE_NETWORK_OPEN_INFORMATION {
  LARGE_INTEGER CreationTime;
  LARGE_INTEGER LastAccessTime;
  LARGE_INTEGER LastWriteTime;
  LARGE_INTEGER ChangeTime;
  LARGE_INTEGER AllocationSize;
  LARGE_INTEGER EndOfFile;
  ULONG         FileAttributes;
} FILE_NETWORK_OPEN_INFORMATION, *PFILE_NETWORK_OPEN_INFORMATION;

NTSTATUS NTAPI ntQueryFullAttributesFile(
  _In_   POBJECT_ATTRIBUTES ObjectAttributes,
  _Out_  PFILE_NETWORK_OPEN_INFORMATION FileInformation
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
    { "CreateProcessW", (PROC)createProcessW }
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
    { "NtQueryDirectoryFile", (PROC)ntQueryDirectoryFile },
    { "NtQueryAttributesFile", (PROC)ntQueryFullAttributesFile },
    { "NtQueryFullAttributesFile", (PROC)ntQueryFullAttributesFile }
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
decltype(&ntClose) origNtClose;
decltype(&ntCreateFile) origNtCreateFile;
decltype(&ntQueryDirectoryFile) origNtQueryDirectoryFile;
decltype(&ntQueryFullAttributesFile) origNtQueryFullAttributesFile;

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

        origCreateProcessA            = getOriginal( &createProcessA            );
        origCreateProcessW            = getOriginal( &createProcessW            );
        origNtClose                   = getOriginal( &ntClose                   );
        origNtCreateFile              = getOriginal( &ntCreateFile              );
        origNtQueryDirectoryFile      = getOriginal( &ntQueryDirectoryFile      );
        origNtQueryFullAttributesFile = getOriginal( &ntQueryFullAttributesFile );
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

    bool hookProcess( HANDLE processHandle, FileMapping const * const * fileMapping, DWORD fileMappingCount, HANDLE thread, bool shouldResume )
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
        return injectLibrary( processHandle, dllNames, initFunc, targetRead,
            writeMappings, &writeMappingsArgs, thread, shouldResume );
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
            wchar_t * fileName = str->Buffer + 4;
            std::size_t fileNameLength = ( str->Length / sizeof(wchar_t) ) - 4;
            MapFilesAPIHook::Data & data( MapFilesAPIHook::getData() );
            
            if ( data.globalMapping.getDir( fileName, fileNameLength, *fileHandle ) )
            {
                ioStatusBlock->Information = FILE_EXISTS;
                return 0;
            }

            UNICODE_STRING tmpStr;
            if ( data.globalMapping.realFile( fileName, fileNameLength, &tmpStr ) )
            {
                PUNICODE_STRING tmp = &tmpStr;
                std::swap( tmp, objectAttributes->ObjectName );
                NTSTATUS result = origNtCreateFile( fileHandle, desiredAccess, objectAttributes,
                    ioStatusBlock, allocationSize, fileAttributes, shareAccess,
                    createDisposition, createOptions, eaBuffer, eaLength );
                objectAttributes->ObjectName = tmp;
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

NTSTATUS NTAPI ntQueryFullAttributesFile(
  _In_   POBJECT_ATTRIBUTES objectAttributes,
  _Out_  PFILE_NETWORK_OPEN_INFORMATION fileInformation
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
            wchar_t * fileName = str->Buffer + 4;
            std::size_t fileNameLength = ( str->Length / sizeof(wchar_t) ) - 4;
            MapFilesAPIHook::Data & data( MapFilesAPIHook::getData() );
            
            HANDLE fileHandle;
            if ( data.globalMapping.getDir( fileName, fileNameLength, fileHandle ) )
            {
                fileInformation->CreationTime.QuadPart   = 0;
                fileInformation->LastAccessTime.QuadPart = 0;
                fileInformation->LastWriteTime.QuadPart  = 0;
                fileInformation->ChangeTime.QuadPart     = 0;
                fileInformation->AllocationSize.QuadPart = 0;
                fileInformation->EndOfFile.QuadPart      = 0;
                fileInformation->FileAttributes = FILE_ATTRIBUTE_DIRECTORY;
                return 0;
            }

            UNICODE_STRING tmpStr;
            if ( data.globalMapping.realFile( fileName, fileNameLength, &tmpStr ) )
            {
                PUNICODE_STRING tmp = &tmpStr;
                std::swap( tmp, objectAttributes->ObjectName );
                NTSTATUS result = origNtQueryFullAttributesFile(
                    objectAttributes, fileInformation );
                objectAttributes->ObjectName = tmp;
                return result;
            }
        }
    }
    return origNtQueryFullAttributesFile( objectAttributes, fileInformation );
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
                fileMappingCount, lpProcessInformation->hThread, shouldResume );
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
                fileMappingCount, lpProcessInformation->hThread, shouldResume );
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

DWORD WINAPI Initialize( HANDLE readHandle, HANDLE initDone )
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
    CloseHandle( readHandle );
    hookWinAPIs();
    if ( initDone )
    {
        SetEvent( initDone );
        WaitForSingleObject( initDone, INFINITE );
        CloseHandle( initDone );
    }
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
