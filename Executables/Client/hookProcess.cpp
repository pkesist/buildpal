#include "hookProcess.hpp"

#include "client.hpp"

#include <apiHooks.hpp>

#include <boost/asio.hpp>
#include <boost/thread.hpp>
#include <boost/mpl/vector.hpp>
#include <boost/mpl/for_each.hpp>

#include <llvm/ADT/StringRef.h>
#include <llvm/Support/FileSystem.h>
#include <llvm/Support/Process.h>

#include <codecvt>
#include <deque>
#include <fstream>
#include <map>
#include <memory>
#include <mutex>

#include <windows.h>
#include <shellapi.h>
#include <psapi.h>

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
    char const * compilerToolset;
    char const * compilerExecutable;
    char const * commandLine;
    char const * currentPath;
    FallbackFunction fallback;
    CreateProcessParams fallbackParams;
    BOOL completed;
    BOOL terminated;
    DWORD exitCode;

    typedef std::deque<std::string> StringSaver;

    DistributedCompileParams() : values( new StringSaver() ) {}

    char const * saveString( std::string const & val )
    {
        return saveString( val.c_str() );
    }

    char const * saveString( char const * val )
    {
        if ( !val ) return val;
        values->push_back( val );
        return values->back().c_str();
    }

private:
    std::shared_ptr<StringSaver> values;
};

typedef llvm::sys::fs::file_status FileStatus;
bool getFileStatus( llvm::StringRef path, FileStatus & result )
{
    return !llvm::sys::fs::status( path, result );
}

struct CompilerExecutables
{
    typedef std::vector<std::pair<FileStatus, std::string> > FileMap;
    FileMap files;

    void registerFile( llvm::StringRef compilerPath )
    {
        FileStatus fileStatus;
        if ( getFileStatus( compilerPath, fileStatus ) )
            files.push_back( std::make_pair( fileStatus, compilerPath ) );
    }
};

typedef std::map<HANDLE, DistributedCompileParams> DistributedCompileParamsInfo;

class HookProcessAPIHookTraits
{
private:
    static BOOL WINAPI createProcessA(
        char const * lpApplicationName,
        char * lpCommandLine,
        LPSECURITY_ATTRIBUTES lpProcessAttributes,
        LPSECURITY_ATTRIBUTES lpThreadAttributes,
        BOOL bInheritHandles,
        DWORD dwCreationFlags,
        LPVOID lpEnvironment,
        char const * lpCurrentDirectory,
        LPSTARTUPINFOA lpStartupInfo,
        LPPROCESS_INFORMATION lpProcessInformation
    );
    static BOOL WINAPI createProcessW(
        wchar_t const * lpApplicationName,
        wchar_t * lpCommandLine,
        LPSECURITY_ATTRIBUTES lpProcessAttributes,
        LPSECURITY_ATTRIBUTES lpThreadAttributes,
        BOOL bInheritHandles,
        DWORD dwCreationFlags,
        LPVOID lpEnvironment,
        wchar_t const * lpCurrentDirectory,
        LPSTARTUPINFOW lpStartupInfo,
        LPPROCESS_INFORMATION lpProcessInformation
    );

    static BOOL WINAPI closeHandle( HANDLE );
    static BOOL WINAPI getExitCodeProcess( HANDLE hProcess, LPDWORD lpExitCode );
    static BOOL WINAPI terminateProcess( HANDLE hProcess, UINT uExitCode );

public:
    static char const moduleName[];
    static APIHookItem const items[]; 
    static unsigned int const itemsCount;

    struct Data
    {
        Data() : portName( "default" ) {}

        CompilerExecutables compilers;
        std::string portName;
        DistributedCompileParamsInfo distributedCompileParamsInfo;
        std::recursive_mutex mutex;
    };
};

char const HookProcessAPIHookTraits::moduleName[] = "kernel32.dll";

APIHookItem const HookProcessAPIHookTraits::items[] = 
{
    { "CreateProcessA"    , (PROC)createProcessA     },
    { "CreateProcessW"    , (PROC)createProcessW     },
    { "GetExitCodeProcess", (PROC)getExitCodeProcess },
    { "CloseHandle"       , (PROC)closeHandle        },
    { "TerminateProcess"  , (PROC)terminateProcess   }
};

unsigned int const HookProcessAPIHookTraits::itemsCount = sizeof(items) / sizeof(items[0]);

typedef APIHooks<HookProcessAPIHookTraits> HookProcessAPIHooks;

bool hookProcess( HANDLE processHandle )
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

    
    HookProcessAPIHookTraits::Data const & hookData( HookProcessAPIHooks::getData() );
    CompilerExecutables::FileMap const & compilerFiles( hookData.compilers.files );

    for
    (
        CompilerExecutables::FileMap::const_iterator iter( compilerFiles.begin() );
        iter != compilerFiles.end();
        ++iter
    )
    {
        DWORD bytesWritten;
        WriteFile( pipeWrite, iter->second.c_str(), iter->second.size() + 1, &bytesWritten, NULL );
        assert( iter->second.size() + 1 == bytesWritten );
    }
    char zero[ 1 ] = { 0 };
    DWORD bytesWritten;
    WriteFile( pipeWrite, zero, 1, &bytesWritten, 0 );
    assert( bytesWritten == 1 );
    WriteFile( pipeWrite, hookData.portName.c_str(), hookData.portName.size() + 1, &bytesWritten, 0 );
    assert( hookData.portName.size() + 1 == bytesWritten );

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
    HookProcessAPIHookTraits::Data & hookData( HookProcessAPIHooks::getData() );
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
                    if ( !readingPortName )
                    {
                        last++;
                        readingPortName = true;
                        continue;
                    }
                }
                std::string const file = remainder + std::string( buffer + last, index - last );
                remainder.clear();
                if ( readingPortName )
                {
                    done = true;
                    hookData.portName = file;
                }
                else
                {
                    hookData.compilers.registerFile( file );
                }
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

    HookProcessAPIHooks::Data & hookData( HookProcessAPIHooks::getData() );
    int result = distributedCompile(
        pdcp->compilerToolset,
        pdcp->compilerExecutable,
        env,
        pdcp->commandLine,
        pdcp->currentPath,
        hookData.portName.c_str(),
        pdcp->fallback,
        &pdcp->fallbackParams
    );
    {
        std::unique_lock<std::recursive_mutex> lock( hookData.mutex );
        DistributedCompileParams & dcp( hookData.distributedCompileParamsInfo[ pdcp->eventHandle ] );
        if ( dcp.terminated )
            return 0;
        hookData.distributedCompileParamsInfo[ pdcp->eventHandle ].completed = TRUE;
        hookData.distributedCompileParamsInfo[ pdcp->eventHandle ].exitCode = (DWORD)result;
    }
    SetEvent( pdcp->eventHandle );
    return 0;
}

bool shortCircuit
(
    wchar_t const * appName,
    wchar_t const * commandLine,
    wchar_t const * currentPath,
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
    HookProcessAPIHooks::Data & hookData( HookProcessAPIHooks::getData() );
    CompilerExecutables::FileMap::const_iterator const end = hookData.compilers.files.end();
    for
    (
        CompilerExecutables::FileMap::const_iterator iter = hookData.compilers.files.begin();
        iter != end;
        ++iter
    )
    {
        if ( llvm::sys::fs::equivalent( iter->first, fileStatus ) )
        {
            compiler = iter->second.c_str();
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
        dcp.compilerToolset = dcp.saveString( "msvc" );
        dcp.compilerExecutable = dcp.saveString( compiler );
        dcp.commandLine = commandLine ? dcp.saveString( convert.to_bytes( commandLine ) ) : 0;
        dcp.currentPath = currentPath ? dcp.saveString( convert.to_bytes( currentPath ) ) : 0;
        dcp.fallback = fallback;
        dcp.fallbackParams = createProcessParams;
        dcp.fallbackParams.eventHandle = eventHandle;

        dcp.completed = FALSE;
        dcp.terminated = FALSE;
        dcp.exitCode = 0;

        HookProcessAPIHooks::Data & hookData( HookProcessAPIHooks::getData() );
        std::unique_lock<std::recursive_mutex> lock( hookData.mutex );
        DistributedCompileParams & _dcp = hookData.distributedCompileParamsInfo[eventHandle];
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

void registerCompiler( char const * compilerPath )
{
    HookProcessAPIHooks::Data & hookData( HookProcessAPIHooks::getData() );
    hookData.compilers.registerFile( compilerPath );
}

void setPortName( char const * portName )
{
    HookProcessAPIHooks::Data & hookData( HookProcessAPIHooks::getData() );
    hookData.portName = portName;
}


BOOL WINAPI HookProcessAPIHookTraits::createProcessA(
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
        lpCurrentDirectory ? convert.from_bytes( lpCurrentDirectory ).c_str() : 0,
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
        hookProcess( lpProcessInformation->hProcess );
        if ( shouldResume )
            ResumeThread( lpProcessInformation->hThread );
    }
    return result;
}

BOOL WINAPI HookProcessAPIHookTraits::createProcessW(
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
    if ( shortCircuit( lpApplicationName, lpCommandLine, lpCurrentDirectory,
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
        hookProcess( lpProcessInformation->hProcess );
        if ( shouldResume )
            ResumeThread( lpProcessInformation->hThread );
    }
    return result;
}

BOOL WINAPI HookProcessAPIHookTraits::getExitCodeProcess( HANDLE hProcess, LPDWORD lpExitCode )
{
    {
        HookProcessAPIHooks::Data & hookData( HookProcessAPIHooks::getData() );
        std::unique_lock<std::recursive_mutex> lock( hookData.mutex );
        DistributedCompileParamsInfo::const_iterator const dcpIter = hookData.distributedCompileParamsInfo.find( hProcess );
        if ( dcpIter != hookData.distributedCompileParamsInfo.end() )
        {
            if ( !dcpIter->second.completed )
                return STILL_ACTIVE;
            *lpExitCode = dcpIter->second.exitCode;
            return TRUE;
        }
    }
    return GetExitCodeProcess( hProcess, lpExitCode );
}

BOOL WINAPI HookProcessAPIHookTraits::closeHandle( HANDLE handle )
{
    {
        HookProcessAPIHooks::Data & hookData( HookProcessAPIHooks::getData() );
        std::unique_lock<std::recursive_mutex> lock( hookData.mutex );
        DistributedCompileParamsInfo::const_iterator const dcpIter = hookData.distributedCompileParamsInfo.find( handle );
        if ( dcpIter != hookData.distributedCompileParamsInfo.end() )
            hookData.distributedCompileParamsInfo.erase( dcpIter );
    }
    return CloseHandle( handle );
}

BOOL WINAPI HookProcessAPIHookTraits::terminateProcess( HANDLE handle, UINT uExitCode )
{
    {
        HookProcessAPIHooks::Data & hookData( HookProcessAPIHooks::getData() );
        std::unique_lock<std::recursive_mutex> lock( hookData.mutex );
        DistributedCompileParamsInfo::iterator const dcpIter = hookData.distributedCompileParamsInfo.find( handle );
        if ( dcpIter != hookData.distributedCompileParamsInfo.end() )
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


BOOL WINAPI DllMain(
  _In_  HINSTANCE hinstDLL,
  _In_  DWORD fdwReason,
  _In_  LPVOID lpvReserved
)
{
    if ( fdwReason == DLL_PROCESS_ATTACH )
    {
        HookProcessAPIHooks::enable();
    }
    else if ( fdwReason == DLL_PROCESS_DETACH )
    {
        HookProcessAPIHooks::disable();
    }
    return TRUE;
}
