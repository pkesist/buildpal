#include "hookProcess.hpp"

#include "client.hpp"

#include <dllInject.hpp>

#include <boost/asio.hpp>
#include <boost/thread.hpp>
#include <boost/mpl/vector.hpp>
#include <boost/mpl/for_each.hpp>

#include <llvm/ADT/StringRef.h>
#include <llvm/Support/FileSystem.h>
#include <llvm/Support/Process.h>

#include <codecvt>
#include <fstream>
#include <map>
#include <mutex>

#include <windows.h>
#include <shellapi.h>
#include <psapi.h>

namespace
{
    BOOL WINAPI closeHandle( HANDLE handle );
    HMODULE WINAPI loadLibraryA( char * lpFileName );
    HMODULE WINAPI loadLibraryW( wchar_t * lpFileName );
    HMODULE WINAPI loadLibraryExA( char * lpFileName, HANDLE hFile, DWORD dwFlags );
    HMODULE WINAPI loadLibraryExW( wchar_t * lpFileName, HANDLE hFile, DWORD dwFlags );
    BOOL WINAPI getExitCodeProcess( HANDLE hProcess, LPDWORD lpExitCode );
    PROC WINAPI getProcAddress( HMODULE hModule, LPCSTR lpProcName );
    BOOL WINAPI terminateProcess( HANDLE handle, UINT uExitCode );
}

PROC replacements[] = 
{
    (PROC)loadLibraryA      ,
    (PROC)loadLibraryW      ,
    (PROC)loadLibraryExA    ,
    (PROC)loadLibraryExW    ,
    (PROC)createProcessA    ,
    (PROC)createProcessW    ,
    (PROC)getExitCodeProcess,
    (PROC)getProcAddress    ,
    (PROC)closeHandle       ,
    (PROC)terminateProcess
};

unsigned int const procCount = sizeof(replacements) / sizeof(PROC);

char const * procNames[procCount] =
{
    "LoadLibraryA",
    "LoadLibraryW",
    "LoadLibraryExA",
    "LoadLibraryExW",
    "CreateProcessA",
    "CreateProcessW",
    "GetExitCodeProcess",
    "GetProcAddress",
    "CloseHandle",
    "TerminateProcess"
};

PROC originals[procCount];

struct CreateProcessParams
{
    void const * lpApplicationName;
    void       * lpCommandLine;
    LPSECURITY_ATTRIBUTES lpProcessAttributes;
    LPSECURITY_ATTRIBUTES lpThreadAttributes;
    BOOL bInheritHandles;
    DWORD dwCreationFlags;
    void       * lpEnvironment;
    void const * lpCurrentDirectory;
    void       * lpStartupInfo;
    LPPROCESS_INFORMATION lpProcessInformation;
    HANDLE eventHandle;
};

struct DistributedCompileParams
{
    HANDLE eventHandle;
    std::string compilerToolset;
    std::string compilerExecutable;
    std::wstring commandLine;
    std::string portName;
    FallbackFunction fallback;
    CreateProcessParams fallbackParams;
    BOOL completed;
    BOOL terminated;
    DWORD exitCode;
};

typedef std::map<HANDLE, DistributedCompileParams> DistributedCompileParamsInfo;
DistributedCompileParamsInfo distributedCompileParamsInfo;

std::recursive_mutex globalMutex;


typedef llvm::sys::fs::file_status FileStatus;

bool getFileStatus( llvm::StringRef path, FileStatus & result )
{
    return !llvm::sys::fs::status( llvm::Twine( path ), result );
}

char const * compilerFiles[] = {
    "C:\\Program Files (x86)\\Microsoft Visual Studio 10.0\\VC\\bin\\cl.exe"             ,
    "C:\\Program Files (x86)\\Microsoft Visual Studio 10.0\\VC\\bin\\amd64\\cl.exe"      ,
    "C:\\Program Files (x86)\\Microsoft Visual Studio 10.0\\VC\\bin\\x86_amd64\\cl.exe"  ,
    "C:\\Program Files (x86)\\Microsoft Visual Studio 11.0\\VC\\bin\\cl.exe"             ,
    "C:\\Program Files (x86)\\Microsoft Visual Studio 11.0\\VC\\bin\\amd64\\cl.exe"      ,
    "C:\\Program Files (x86)\\Microsoft Visual Studio 11.0\\VC\\bin\\x86_amd64\\cl.exe"  ,
    "C:\\Program Files (x86)\\Microsoft Visual Studio 11.0\\VC\\bin\\x86_arm\\cl.exe"    ,
    "C:\\Program Files (x86)\\Microsoft Visual Studio 9.0\\VC\\bin\\cl.exe"              ,
    "C:\\Program Files (x86)\\Microsoft Visual Studio 9.0\\VC\\bin\\amd64\\cl.exe"       ,
    "C:\\Program Files (x86)\\Microsoft Visual Studio 9.0\\VC\\bin\\x86_amd64\\cl.exe"   ,
    "C:\\Program Files (x86)\\Microsoft Visual Studio 9.0\\VC\\bin\\x86_ia64\\cl.exe"    ,
    "C:\\Program Files (x86)\\Microsoft Visual Studio 9.0\\VC\\ce\\bin\\x86_arm\\cl.exe" ,
    "C:\\Program Files (x86)\\Microsoft Visual Studio 9.0\\VC\\ce\\bin\\x86_mips\\cl.exe",
    "C:\\Program Files (x86)\\Microsoft Visual Studio 9.0\\VC\\ce\\bin\\x86_sh\\cl.exe"
};

std::size_t const compilerFilesCount = sizeof(compilerFiles) / sizeof(compilerFiles[0]);

char const portName[] = "default";

struct CompilerExecutables
{
    typedef std::vector<std::pair<FileStatus, char const *> > FileMap;
    FileMap files;

    CompilerExecutables()
    {
        for ( std::size_t index( 0 ); index < compilerFilesCount; ++index )
        {
            FileStatus fileStatus;
            if ( getFileStatus( compilerFiles[ index ], fileStatus ) )
                files.push_back( std::make_pair( fileStatus, compilerFiles[ index ] ) );
        }
    }
} compilerExecutables;


bool hookProcess( HANDLE processHandle, char const * * compilerFiles, std::size_t compilerFilesCount, char const * portName )
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

    for ( std::size_t index( 0 ); index < compilerFilesCount; ++index )
    {
        DWORD const bytesToWrite = strlen(compilerFiles[index]) + 1;
        DWORD bytesWritten;
        WriteFile( pipeWrite, compilerFiles[index], bytesToWrite, &bytesWritten, NULL );
        assert( bytesToWrite == bytesWritten );
    }
    char zero[ 1 ] = { 0 };
    DWORD bytesWritten;
    WriteFile( pipeWrite, zero, 1, &bytesWritten, 0 );
    assert( bytesWritten == 1 );
    DWORD const bytesToWrite = strlen(portName) + 1;
    WriteFile( pipeWrite, portName, strlen(portName) + 1, &bytesWritten, 0 );
    assert( bytesToWrite == bytesWritten );

    char const * dllNames[] = {
        "bp_cli_inj32.dll",
        "bp_cli_inj64.dll"
    };
    char const initFunc[] = "Initialize";

    return injectLibrary( processHandle, dllNames, initFunc, targetRead );
}

DWORD WINAPI Initialize( HANDLE pipeHandle )
{
    bool readingPortName = false;
    bool done = false;
    while ( !done )
    {
        char buffer[ 1024 ];
        DWORD last = 0;
        DWORD read;
        ReadFile( pipeHandle, buffer, 1024, &read, 0 );
        std::string remainder;
        for ( DWORD index( 0 ); index < read; ++index )
        {
            if ( buffer[ index ] == '\0' )
            {
                if ( last == index )
                {
                    last++;
                    readingPortName = true;
                    continue;
                }
                std::string file = remainder + std::string( buffer + last, index - last );
                remainder.clear();
                if ( readingPortName )
                    done = true;
                last = index + 1;
            }
        }
        remainder += std::string( buffer + last, read - last );
    }
    return 0;
}

DWORD WINAPI distributedCompileWorker( void * params )
{
    DistributedCompileParams * pdcp = (DistributedCompileParams *)params;
    Environment env( pdcp->fallbackParams.lpEnvironment, ( pdcp->fallbackParams.dwCreationFlags | CREATE_UNICODE_ENVIRONMENT ) != 0 );

    int result = distributedCompile(
        pdcp->compilerToolset,
        pdcp->compilerExecutable,
        env,
        pdcp->commandLine.c_str(),
        pdcp->portName,
        pdcp->fallback,
        &pdcp->fallbackParams
    );
    HANDLE eventHandle = pdcp->eventHandle;
    {
        std::unique_lock<std::recursive_mutex> lock( globalMutex );
        DistributedCompileParams & dcp( distributedCompileParamsInfo[ eventHandle ] );
        if ( dcp.terminated )
            return 0;
        distributedCompileParamsInfo[ eventHandle ].completed = TRUE;
        distributedCompileParamsInfo[ eventHandle ].exitCode = (DWORD)result;
    }
    SetEvent( eventHandle );
    return 0;
}

bool shortCircuit
(
    wchar_t const * appName,
    wchar_t const * commandLine,
    FallbackFunction fallback,
    CreateProcessParams const & createProcessParams
)
{
    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    FileStatus fileStatus;
    bool haveStatus = false;
    std::string args;
    if ( appName )
    {
        haveStatus = getFileStatus( convert.to_bytes( appName ), fileStatus );
    }
    else
    {
        int argc;
        wchar_t * * argv = CommandLineToArgvW( commandLine, &argc );
        wchar_t buffer[ MAX_PATH ];
        wchar_t * bufferEnd;
        DWORD length = ::SearchPathW( NULL, argv[0], L".exe", MAX_PATH, buffer, &bufferEnd );
        if ( length )
        {
            std::string const executable = convert.to_bytes( buffer );
            haveStatus = getFileStatus( executable, fileStatus );
        }
    }

    if ( !haveStatus )
        return false;

    char const * compiler = NULL;
    CompilerExecutables::FileMap::const_iterator const end = compilerExecutables.files.end();
    for
    (
        CompilerExecutables::FileMap::const_iterator iter = compilerExecutables.files.begin();
        iter != end;
        ++iter
    )
    {
        if ( llvm::sys::fs::equivalent( iter->first, fileStatus ) )
        {
            compiler = iter->second;
            break;
        }
    }

    if ( !compiler )
        return false;

    // We will use this as a result - it is waitable.
    HANDLE eventHandle = CreateEvent( NULL, TRUE, FALSE, NULL );

    DistributedCompileParams * pDcp;
    {
        DistributedCompileParams dcp;
        dcp.eventHandle = eventHandle;
        dcp.compilerToolset = "msvc";
        dcp.compilerExecutable = compiler;
        dcp.commandLine = commandLine;
        dcp.portName = portName;
        dcp.fallback = fallback;
        dcp.fallbackParams = createProcessParams;
        dcp.fallbackParams.eventHandle = eventHandle;

        dcp.completed = FALSE;
        dcp.terminated = FALSE;
        dcp.exitCode = 0;

        std::unique_lock<std::recursive_mutex> lock( globalMutex );
        DistributedCompileParams & _dcp = distributedCompileParamsInfo[eventHandle];
        _dcp = dcp;
        pDcp = &_dcp;
    }

    // When faking process id - use a ridiculously large number.
    DWORD processId = 0x80000000 | ( (DWORD)eventHandle >> 1 );

    DWORD threadId;
    HANDLE threadHandle = CreateThread(
        NULL,
        64 * 1024,
        &distributedCompileWorker,
        pDcp,
        createProcessParams.dwCreationFlags & CREATE_SUSPENDED ? CREATE_SUSPENDED :  0,
        &threadId
    );
    createProcessParams.lpProcessInformation->hProcess = eventHandle;
    createProcessParams.lpProcessInformation->hThread = threadHandle;
    createProcessParams.lpProcessInformation->dwProcessId = processId;
    createProcessParams.lpProcessInformation->dwThreadId = threadId;

    // fallback should be real createprocess
    // we must return handle
    // the handle must be waitable
    // must hook GetExitCodeProcess
    // must fake process id
    // getting handle for process id must return handle
    return true;
}

int createProcessFallbackA( void * params )
{
    PROCESS_INFORMATION processInfo;
    CreateProcessParams * cpp = (CreateProcessParams *)params;
    BOOL const cpResult = CreateProcessA(
        static_cast<char const *>( cpp->lpApplicationName ),
        static_cast<char       *>( cpp->lpCommandLine ),
        cpp->lpProcessAttributes,
        cpp->lpThreadAttributes,
        cpp->bInheritHandles,
        cpp->dwCreationFlags,
        cpp->lpEnvironment,
        static_cast<char const *>( cpp->lpCurrentDirectory ),
        static_cast<LPSTARTUPINFOA>( cpp->lpStartupInfo ),
        &processInfo
    );
    if ( !cpResult )
    {
        // This is really bad. We already told the user that we successfully
        // created the process, and now the fallback failed to do that.
        // Best we can do is return some error code and walk away whistling.
        return -1;
    }
    WaitForSingleObject( processInfo.hProcess, INFINITE );
    std::int32_t result;
    GetExitCodeProcess( processInfo.hProcess, (DWORD *)&result );
    CloseHandle( processInfo.hThread );
    CloseHandle( processInfo.hProcess );
    return result;
}

int createProcessFallbackW( void * params )
{
    PROCESS_INFORMATION processInfo;
    CreateProcessParams * cpp = (CreateProcessParams *)params;
    BOOL const cpResult = CreateProcessW(
        static_cast<wchar_t const *>( cpp->lpApplicationName ),
        static_cast<wchar_t       *>( cpp->lpCommandLine ),
        cpp->lpProcessAttributes,
        cpp->lpThreadAttributes,
        cpp->bInheritHandles,
        cpp->dwCreationFlags,
        cpp->lpEnvironment,
        static_cast<wchar_t const *>( cpp->lpCurrentDirectory ),
        static_cast<LPSTARTUPINFOW>( cpp->lpStartupInfo ),
        &processInfo
    );
    if ( !cpResult )
    {
        // See above.
        return -1;
    }
    WaitForSingleObject( processInfo.hProcess, INFINITE );
    std::int32_t result;
    GetExitCodeProcess( processInfo.hProcess, (DWORD *)&result );
    CloseHandle( processInfo.hThread );
    CloseHandle( processInfo.hProcess );
    return result;
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
    CreateProcessParams const cpParams = 
    {
        lpApplicationName,
        lpCommandLine,
        lpProcessAttributes,
        lpThreadAttributes,
        bInheritHandles,
        dwCreationFlags,
        lpEnvironment,
        lpCurrentDirectory,
        lpStartupInfo,
        lpProcessInformation
    };

    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    if ( shortCircuit(
        lpApplicationName ? convert.from_bytes( lpApplicationName ).c_str() : 0,
        lpCommandLine ? convert.from_bytes( lpCommandLine ).c_str() : 0,
        createProcessFallbackA, cpParams ) )
        return 1;

    bool const shouldResume = (dwCreationFlags & CREATE_SUSPENDED) == 0;
    BOOL result = CreateProcessA( 
        lpApplicationName,
        lpCommandLine,
        lpProcessAttributes,
        lpThreadAttributes,
        bInheritHandles,
        dwCreationFlags | CREATE_SUSPENDED,
        lpEnvironment,
        lpCurrentDirectory,
        lpStartupInfo,
        lpProcessInformation
    );
    if ( result )
    {
        hookProcess( lpProcessInformation->hProcess, compilerFiles, compilerFilesCount, portName );
        if ( shouldResume )
            ResumeThread( lpProcessInformation->hThread );
    }
    return result;
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
    CreateProcessParams cpParams = 
    {
        lpApplicationName,
        lpCommandLine,
        lpProcessAttributes,
        lpThreadAttributes,
        bInheritHandles,
        dwCreationFlags,
        lpEnvironment,
        lpCurrentDirectory,
        lpStartupInfo,
        lpProcessInformation
    };
    if ( shortCircuit( lpApplicationName, lpCommandLine,
            createProcessFallbackW, cpParams ) )
        return 1;

    bool const shouldResume = (dwCreationFlags & CREATE_SUSPENDED) == 0;
    BOOL result = CreateProcessW( 
        lpApplicationName,
        lpCommandLine,
        lpProcessAttributes,
        lpThreadAttributes,
        bInheritHandles,
        dwCreationFlags | CREATE_SUSPENDED,
        lpEnvironment,
        lpCurrentDirectory,
        lpStartupInfo,
        lpProcessInformation
    );
    if ( result )
    {
        hookProcess( lpProcessInformation->hProcess, compilerFiles, compilerFilesCount, portName );
        if ( shouldResume )
            ResumeThread( lpProcessInformation->hThread );
    }
    return result;
}

namespace
{
    HMODULE WINAPI loadLibraryA( char * lpFileName )
    {
        HMODULE result = ::LoadLibraryA( lpFileName );
        hookWinAPI( originals, replacements, procCount );
        return result;
    }

    HMODULE WINAPI loadLibraryW( wchar_t * lpFileName )
    {
        std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
        HMODULE result = ::LoadLibraryW( lpFileName );
        hookWinAPI( originals, replacements, procCount );
        return result;
    }

    HMODULE WINAPI loadLibraryExA( char * lpFileName, HANDLE hFile, DWORD dwFlags )
    {
        HMODULE result = ::LoadLibraryExA( lpFileName, hFile, dwFlags );
        hookWinAPI( originals, replacements, procCount );
        return result;
    }

    HMODULE WINAPI loadLibraryExW( wchar_t * lpFileName, HANDLE hFile, DWORD dwFlags )
    {
        std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
        HMODULE result = ::LoadLibraryExW( lpFileName, hFile, dwFlags );
        hookWinAPI( originals, replacements, procCount );
        return result;
    }

    BOOL WINAPI getExitCodeProcess( HANDLE hProcess, LPDWORD lpExitCode )
    {
        {
            std::unique_lock<std::recursive_mutex> lock( globalMutex );
            DistributedCompileParamsInfo::const_iterator const dcpIter = distributedCompileParamsInfo.find( hProcess );
            if ( dcpIter != distributedCompileParamsInfo.end() )
            {
                if ( !dcpIter->second.completed )
                    return STILL_ACTIVE;
                *lpExitCode = dcpIter->second.exitCode;
                return TRUE;
            }
        }
        return GetExitCodeProcess( hProcess, lpExitCode );
    }

    PROC WINAPI getProcAddress( HMODULE hModule, LPCSTR lpProcName )
    {
        PROC result = GetProcAddress( hModule, lpProcName );
        for ( unsigned int index( 0 ); index < procCount; ++index )
            if ( result == originals[ index ] )
                return replacements[ index ];
        return result;
    }

    BOOL WINAPI closeHandle( HANDLE handle )
    {
        {
            std::unique_lock<std::recursive_mutex> lock( globalMutex );
            DistributedCompileParamsInfo::const_iterator const dcpIter = distributedCompileParamsInfo.find( handle );
            if ( dcpIter != distributedCompileParamsInfo.end() )
                distributedCompileParamsInfo.erase( dcpIter );
        }
        return CloseHandle( handle );
    }

    BOOL WINAPI terminateProcess( HANDLE handle, UINT uExitCode )
    {
        {
            std::unique_lock<std::recursive_mutex> lock( globalMutex );
            DistributedCompileParamsInfo::iterator const dcpIter = distributedCompileParamsInfo.find( handle );
            if ( dcpIter != distributedCompileParamsInfo.end() )
            {
                dcpIter->second.terminated = TRUE;
                dcpIter->second.exitCode = uExitCode;
                lock.unlock();
                SetEvent( handle );
                return TRUE;
            }
        }
        return TerminateProcess( handle, uExitCode );
    }
}  // anonymous namespace


BOOL WINAPI DllMain(
  _In_  HINSTANCE hinstDLL,
  _In_  DWORD fdwReason,
  _In_  LPVOID lpvReserved
)
{
    if ( fdwReason == DLL_PROCESS_ATTACH )
    {
        HMODULE kernel32Handle = ::GetModuleHandle( "Kernel32.dll" );
        for ( unsigned int index( 0 ); index < procCount; ++index )
            originals[ index ] = GetProcAddress( kernel32Handle, procNames[ index ] );
        hookWinAPI( originals, replacements, procCount );
    }
    else if ( fdwReason == DLL_PROCESS_DETACH )
    {
        hookWinAPI( replacements, originals, procCount );
    }
    return TRUE;
}
