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

struct StartupInfo
{
    DWORD  cb;
    void * lpReserved;
    void * lpDesktop;
    void * lpTitle;
    DWORD  dwX;
    DWORD  dwY;
    DWORD  dwXSize;
    DWORD  dwYSize;
    DWORD  dwXCountChars;
    DWORD  dwYCountChars;
    DWORD  dwFillAttribute;
    DWORD  dwFlags;
    WORD   wShowWindow;
    WORD   cbReserved2;
    LPBYTE lpReserved2;
    HANDLE hStdInput;
    HANDLE hStdOutput;
    HANDLE hStdError;
};

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
    StartupInfo startupInfo;
    LPPROCESS_INFORMATION lpProcessInformation;
};

class DistributedCompileParams
{
    std::deque<std::vector<unsigned char> > stringSaver_;

    HANDLE eventHandle_;
    char const * compilerToolset_;
    char const * compilerExecutable_;
    char const * commandLine_;
    char const * currentPath_;
    FallbackFunction fallback_;
    Environment environment_;
    CreateProcessParams createProcessParams_;
    bool completed_;
    bool terminated_;
    DWORD exitCode_;
    HANDLE stdOutHandle_;
    HANDLE stdErrHandle_;

    template <typename T>
    T * saveString( T const * ptr, std::size_t size )
    {
        if ( !ptr )
            return 0;
        unsigned char const * start = reinterpret_cast<unsigned char const *>( ptr );
        stringSaver_.push_back( std::vector<unsigned char>( start, start + size * sizeof(T) ) );
        return reinterpret_cast<T *>( &stringSaver_.back()[0] );
    }

    wchar_t * saveStringW( wchar_t * ptr )
    {
        return saveString<wchar_t>( ptr, ptr ? wcslen( ptr ) + 1 : 0 );
    }

    char const * saveStringA( char const * str )
    {
        return saveString<char>( str, str ? strlen( str ) + 1 : 0 );
    }

    void storeCreateProcessParams( CreateProcessParams const & cpParams, bool const wide )
    {
        // Save all strings, as they might go out of scope by the time we execute
        // fallback.
        typedef void * (DistributedCompileParams::* StringSaver)(void const *);
        StringSaver stringSaver = wide
            ? (StringSaver)(&DistributedCompileParams::saveStringW)
            : (StringSaver)(&DistributedCompileParams::saveStringA)
        ;
        createProcessParams_.lpApplicationName = (this->*stringSaver)(cpParams.lpApplicationName);
        createProcessParams_.lpCommandLine = (this->*stringSaver)(cpParams.lpCommandLine);
        createProcessParams_.lpProcessAttributes = cpParams.lpProcessAttributes;
        createProcessParams_.lpThreadAttributes = cpParams.lpThreadAttributes;
        createProcessParams_.bInheritHandles = cpParams.bInheritHandles;
        createProcessParams_.dwCreationFlags = cpParams.dwCreationFlags;
        createProcessParams_.lpEnvironment = cpParams.lpEnvironment;
        createProcessParams_.lpCurrentDirectory = cpParams.lpCurrentDirectory;
        createProcessParams_.startupInfo = cpParams.startupInfo;

        createProcessParams_.startupInfo.lpReserved = (this->*stringSaver)(createProcessParams_.startupInfo.lpReserved);
        createProcessParams_.startupInfo.lpDesktop  = (this->*stringSaver)(createProcessParams_.startupInfo.lpDesktop );
        createProcessParams_.startupInfo.lpTitle    = (this->*stringSaver)(createProcessParams_.startupInfo.lpTitle   );
        createProcessParams_.lpProcessInformation = cpParams.lpProcessInformation;

        StartupInfo const * startupInfo = &createProcessParams_.startupInfo;
        bool const hookHandles( ( startupInfo->dwFlags & STARTF_USESTDHANDLES ) != 0 );
        if ( hookHandles )
        {
            HANDLE const currentProcess = GetCurrentProcess(); 
            if ( startupInfo->hStdOutput != INVALID_HANDLE_VALUE )
            {
                DuplicateHandle( currentProcess, startupInfo->hStdOutput,
                    currentProcess, &stdOutHandle_, 0, FALSE,
                    DUPLICATE_SAME_ACCESS );
                createProcessParams_.startupInfo.hStdError = stdOutHandle_;
            }

            if ( startupInfo->hStdError != INVALID_HANDLE_VALUE )
            {
                DuplicateHandle( currentProcess, startupInfo->hStdError,
                    currentProcess, &stdErrHandle_, 0, FALSE,
                    DUPLICATE_SAME_ACCESS );
            }
            createProcessParams_.startupInfo.hStdError = stdErrHandle_;
        }
    }

private:
    // Noncopyable
    DistributedCompileParams( DistributedCompileParams const & );
    DistributedCompileParams operator=( DistributedCompileParams const & );
    DistributedCompileParams( DistributedCompileParams && );
    DistributedCompileParams operator=( DistributedCompileParams && );

public:
    DistributedCompileParams
    (
        HANDLE eventHandle,
        char const * compilerToolset,
        char const * compilerExecutable,
        char const * commandLine,
        char const * currentPath,
        FallbackFunction fallback,
        CreateProcessParams const & createProcessParams,
        bool wide
    )
        :
        eventHandle_( eventHandle ),
        compilerToolset_( saveStringA( compilerToolset ) ),
        compilerExecutable_( saveStringA( compilerExecutable ) ),
        commandLine_( saveStringA( commandLine ) ),
        currentPath_( saveStringA( currentPath ) ),
        environment_( createProcessParams.lpEnvironment,
            ( createProcessParams.dwCreationFlags |
            CREATE_UNICODE_ENVIRONMENT ) != 0 ),
        fallback_( fallback ),
        completed_( false ),
        terminated_( false ),
        exitCode_( 0 ),
        stdOutHandle_( 0 ),
        stdErrHandle_( 0 )
    {
        storeCreateProcessParams( createProcessParams, wide );
    }

    HANDLE eventHandle() const { return eventHandle_; }
    char const * compilerToolset() const { return compilerToolset_; }
    char const * compilerExecutable() const { return compilerExecutable_; }
    char const * commandLine() const { return commandLine_; }
    char const * currentPath() const { return currentPath_; }
    FallbackFunction fallback() const { return fallback_; }
    CreateProcessParams * cpParams() { return &createProcessParams_; }
    Environment & environment() { return environment_; }
    HANDLE stdOutHandle() const { return stdOutHandle_; }
    HANDLE stdErrHandle() const { return stdErrHandle_; }

    bool complete( DWORD exitCode )
    {
        if ( stdOutHandle_ ) CloseHandle( stdOutHandle_ );
        if ( stdErrHandle_ ) CloseHandle( stdErrHandle_ );
        if ( terminated_ )
            return false;
        completed_ = true;
        exitCode_ = (DWORD)exitCode;
        return true;
    }

    void terminate( DWORD exitCode )
    {
        if ( stdOutHandle_ ) CloseHandle( stdOutHandle_ );
        if ( stdErrHandle_ ) CloseHandle( stdErrHandle_ );
        terminated_ = true;
        exitCode_ = (DWORD)exitCode;
    }

    bool completed() const { return completed_; }
    bool terminated() const { return terminated_; }
    DWORD exitCode() const { return exitCode_; }
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

typedef std::shared_ptr<DistributedCompileParams> DistributedCompileParamsPtr;
typedef std::map<HANDLE, DistributedCompileParamsPtr> DistributedCompileParamsInfo;

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
    static VOID WINAPI exitProcess( UINT uExitCode );

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
    { "TerminateProcess"  , (PROC)terminateProcess   },
    { "ExitProcess"       , (PROC)exitProcess        }
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

    HookProcessAPIHooks::Data & hookData( HookProcessAPIHooks::getData() );
    int result = distributedCompile(
        pdcp->compilerToolset(),
        pdcp->compilerExecutable(),
        pdcp->environment(),
        pdcp->commandLine(),
        pdcp->currentPath(),
        hookData.portName.c_str(),
        pdcp->fallback(),
        pdcp,
        pdcp->stdOutHandle(),
        pdcp->stdErrHandle()
    );
    {
        std::unique_lock<std::recursive_mutex> lock( hookData.mutex );
        if ( !pdcp->complete( (DWORD)result ) )
            return 0;
    }
    SetEvent( pdcp->eventHandle() );
    return 0;
}

bool shortCircuit
(
    wchar_t const * appName,
    wchar_t const * commandLine,
    wchar_t const * currentPath,
    FallbackFunction fallback,
    CreateProcessParams const & createProcessParams,
    bool wide
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

    DistributedCompileParamsPtr const pDcp(
        new DistributedCompileParams(
            eventHandle,
            "msvc",
            compiler,
            commandLine ? convert.to_bytes( commandLine ).c_str() : 0,
            currentPath ? convert.to_bytes( currentPath ).c_str() : 0,
            fallback,
            createProcessParams,
            wide
        )
    );

    {
        std::unique_lock<std::recursive_mutex> lock( hookData.mutex );
        hookData.distributedCompileParamsInfo.insert( std::make_pair( eventHandle, pDcp ) );
    }

    // When faking process id - use a ridiculously large number.
    DWORD processId = 0x80000000 | ( (DWORD)eventHandle >> 1 );

    DWORD threadId;
    HANDLE threadHandle = CreateThread(
        NULL,
        64 * 1024,
        &distributedCompileWorker,
        pDcp.get(),
        createProcessParams.dwCreationFlags & CREATE_SUSPENDED ? CREATE_SUSPENDED :  0,
        &threadId
    );
    createProcessParams.lpProcessInformation->hProcess = eventHandle;
    createProcessParams.lpProcessInformation->hThread = threadHandle;
    createProcessParams.lpProcessInformation->dwProcessId = processId;
    createProcessParams.lpProcessInformation->dwThreadId = threadId;
    return true;
}

int createProcessFallbackA( void * params )
{
    DistributedCompileParams * pdcp = (DistributedCompileParams *)params;
    PROCESS_INFORMATION processInfo;
    CreateProcessParams * cpp = pdcp->cpParams();
    BOOL const cpResult = CreateProcessA(
        static_cast<char const *>( cpp->lpApplicationName ),
        static_cast<char       *>( cpp->lpCommandLine ),
        cpp->lpProcessAttributes,
        cpp->lpThreadAttributes,
        cpp->bInheritHandles,
        cpp->dwCreationFlags & (~CREATE_SUSPENDED), // No longer suspended.
        cpp->lpEnvironment,
        static_cast<char const *>( cpp->lpCurrentDirectory ),
        reinterpret_cast<LPSTARTUPINFOA>( &cpp->startupInfo ),
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
    DistributedCompileParams * pdcp = (DistributedCompileParams *)params;
    PROCESS_INFORMATION processInfo;
    CreateProcessParams * cpp = pdcp->cpParams();
    BOOL const cpResult = CreateProcessW(
        static_cast<wchar_t const *>( cpp->lpApplicationName ),
        static_cast<wchar_t       *>( cpp->lpCommandLine ),
        cpp->lpProcessAttributes,
        cpp->lpThreadAttributes,
        cpp->bInheritHandles,
        cpp->dwCreationFlags & (~CREATE_SUSPENDED), // No longer suspended.
        cpp->lpEnvironment,
        static_cast<wchar_t const *>( cpp->lpCurrentDirectory ),
        reinterpret_cast<LPSTARTUPINFOW>( &cpp->startupInfo ),
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
        *((StartupInfo *)lpStartupInfo),
        lpProcessInformation
    };

    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    if ( shortCircuit(
        lpApplicationName ? convert.from_bytes( lpApplicationName ).c_str() : 0,
        lpCommandLine ? convert.from_bytes( lpCommandLine ).c_str() : 0,
        lpCurrentDirectory ? convert.from_bytes( lpCurrentDirectory ).c_str() : 0,
        createProcessFallbackA, cpParams, false ) )
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
        *((StartupInfo *)lpStartupInfo),
        lpProcessInformation
    };
    if ( shortCircuit( lpApplicationName, lpCommandLine, lpCurrentDirectory,
            createProcessFallbackW, cpParams, true ) )
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
            if ( !dcpIter->second->completed() )
                return STILL_ACTIVE;
            *lpExitCode = dcpIter->second->exitCode();
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
            dcpIter->second->terminate( uExitCode );
            lock.unlock();
            SetEvent( handle );
            return TRUE;
        }
    }
    return TerminateProcess( handle, uExitCode );
}

VOID WINAPI HookProcessAPIHookTraits::exitProcess( UINT uExitCode )
{
    HookProcessAPIHooks::disable();
    return ExitProcess( uExitCode );
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
