#include "hookProcess.hpp"

#include "../../Extensions/Client/client.hpp"

#include <apiHooks.hpp>

#include <boost/asio.hpp>
#include <boost/thread.hpp>

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

class DistributedCompilation;
typedef std::shared_ptr<DistributedCompilation> DistributedCompilationPtr;
typedef std::map<HANDLE, DistributedCompilationPtr> DistributedCompilationInfo;

class HookProcessAPIHookDesc
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
        DistributedCompilationInfo distributedCompilationInfo;
        std::recursive_mutex mutex;
    };
};

char const HookProcessAPIHookDesc::moduleName[] = "kernel32.dll";

APIHookItem const HookProcessAPIHookDesc::items[] = 
{
    { "CreateProcessA"    , (PROC)createProcessA     },
    { "CreateProcessW"    , (PROC)createProcessW     },
    { "GetExitCodeProcess", (PROC)getExitCodeProcess },
    { "CloseHandle"       , (PROC)closeHandle        },
    { "TerminateProcess"  , (PROC)terminateProcess   },
    { "ExitProcess"       , (PROC)exitProcess        }
};

unsigned int const HookProcessAPIHookDesc::itemsCount = sizeof(items) / sizeof(items[0]);

typedef APIHooks<HookProcessAPIHookDesc> HookProcessAPIHooks;

template <typename CharType>
class StringSaver
{
    typedef std::basic_string<CharType> StringType;
    typedef std::deque<StringType> Storage;
    Storage storage_;

public:
    CharType * save( CharType const * str )
    {
        if ( !str ) return NULL;
        storage_.push_back( str );
        return &storage_.back()[ 0 ];
    }
};

typedef std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> WideConverter;

struct StartupInfoEx : public STARTUPINFOW
{
    StartupInfoEx( LPSTARTUPINFOA si, StringSaver<wchar_t> & s, WideConverter & c )
    {
        static_cast<STARTUPINFOW &>( *this ) = *reinterpret_cast<LPSTARTUPINFOW>( si );
        this->lpReserved = widen( s, c, si->lpReserved );
        this->lpDesktop = widen( s, c, si->lpDesktop );
        this->lpTitle = widen( s, c, si->lpTitle );
    }

    StartupInfoEx( LPSTARTUPINFOW si )
    {
        static_cast<STARTUPINFOW &>( *this ) = *si;
    }

    void saveInfo( StringSaver<wchar_t> & saver )
    {
        lpReserved = saver.save( lpReserved );
        lpDesktop = saver.save( lpDesktop );
        lpTitle = saver.save( lpTitle );
    }

    static wchar_t * widen( StringSaver<wchar_t> & saver, WideConverter & converter, char const * str )
    {
        if ( !str )
            return NULL;
        return saver.save( converter.from_bytes( str ).c_str() );
    }
};

struct CreateProcessParams
{
    typedef std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> WideConverter;

    bool savedInfo_;
    bool stringsCopied_;

    CreateProcessParams( char const * appName, char * commandLine,
        LPSECURITY_ATTRIBUTES procAttr, LPSECURITY_ATTRIBUTES threadAttr,
        BOOL inherit, DWORD flags, void * env, char const * curDir,
        LPSTARTUPINFOA pStartupInfo )
        :
        savedInfo_( false ),
        stringSaver_( new StringSaver<wchar_t>() ),
        stringsCopied_( true ),
        lpApplicationName( widen( appName ) ),
        lpCommandLine( widen( commandLine ) ),
        lpProcessAttributes( procAttr ),
        lpThreadAttributes( threadAttr ),
        bInheritHandles( inherit ),
        dwCreationFlags( flags ),
        environment( env, ( flags & CREATE_UNICODE_ENVIRONMENT ) != 0 ),
        lpCurrentDirectory( widen( curDir ) ),
        startupInfo( pStartupInfo, *stringSaver_, converter_ )
    {
    }

    CreateProcessParams( wchar_t const * appName, wchar_t * commandLine,
        LPSECURITY_ATTRIBUTES procAttr, LPSECURITY_ATTRIBUTES threadAttr,
        BOOL inherit, DWORD flags, void * env, wchar_t const * curDir,
        LPSTARTUPINFOW pStartupInfo )
        :
        savedInfo_( false ),
        stringsCopied_( false ),
        lpApplicationName( appName ),
        lpCommandLine( commandLine ),
        lpProcessAttributes( procAttr ),
        lpThreadAttributes( threadAttr ),
        bInheritHandles( inherit ),
        dwCreationFlags( flags ),
        environment( env, ( flags & CREATE_UNICODE_ENVIRONMENT ) != 0 ),
        lpCurrentDirectory( curDir ),
        startupInfo( pStartupInfo )
    {
    }

    ~CreateProcessParams()
    {
        if ( savedInfo_ )
        {
            CloseHandle( startupInfo.hStdOutput );
            CloseHandle( startupInfo.hStdError );
        }
    }

    std::shared_ptr<StringSaver<wchar_t> > stringSaver_;
    WideConverter converter_;
    wchar_t const * lpApplicationName;
    wchar_t * lpCommandLine;
    LPSECURITY_ATTRIBUTES lpProcessAttributes;
    LPSECURITY_ATTRIBUTES lpThreadAttributes;
    BOOL bInheritHandles;
    DWORD dwCreationFlags;
    Environment environment;
    wchar_t const * lpCurrentDirectory;
    StartupInfoEx startupInfo;

    void saveInfo()
    {
        if ( savedInfo_ )
            return;

        savedInfo_ = true;

        // Ignore STARTUPINFOEX, use only STARTUPINFO.
        // It would be a nightmare to keep the extended part alive until we
        // (might) need it. At this point we are certain that we are running
        // the compiler, so just slice off the extended part.
        //
        // Note that we could just copy the EX pointer and hope that the target
        // structure does not go out of scope. It seems to work in practice,
        // but I'd rather not.
        dwCreationFlags &= ~EXTENDED_STARTUPINFO_PRESENT;

        // Remove suspended flag
        dwCreationFlags &= ~CREATE_SUSPENDED;

        // We will always send narrow environment.
        dwCreationFlags &= ~CREATE_UNICODE_ENVIRONMENT;

        // Store current directory. The caller might change it by the time we
        // spawn worker thread. (CMake does that)
        if ( !lpCurrentDirectory )
        {
            DWORD size( GetCurrentDirectoryW( 0, NULL ) );
            wchar_t * curPath = static_cast<wchar_t *>( alloca( size * sizeof(wchar_t) ) );
            GetCurrentDirectoryW( size, curPath );
            if ( stringsCopied_ )
                lpCurrentDirectory = store( curPath );
            else
                lpCurrentDirectory = curPath;
        }

        // Store stdout/stderr handles. Create duplicates, as user is free to
        // close handles after successful CreateProcess call.
        bool const hookHandles( ( startupInfo.dwFlags & STARTF_USESTDHANDLES ) != 0 );
        startupInfo.dwFlags |= STARTF_USESTDHANDLES;
        HANDLE const currentProcess = GetCurrentProcess(); 
        if ( !hookHandles || ( startupInfo.hStdOutput == INVALID_HANDLE_VALUE ) )
            startupInfo.hStdOutput =  GetStdHandle( STD_OUTPUT_HANDLE );
        DuplicateHandle( currentProcess, startupInfo.hStdOutput,
            currentProcess, &startupInfo.hStdOutput, 0, TRUE,
            DUPLICATE_SAME_ACCESS );

        if ( !hookHandles || ( startupInfo.hStdError == INVALID_HANDLE_VALUE ) )
            startupInfo.hStdError = GetStdHandle( STD_ERROR_HANDLE );
        DuplicateHandle( currentProcess, startupInfo.hStdError,
            currentProcess, &startupInfo.hStdError, 0, TRUE,
            DUPLICATE_SAME_ACCESS );

        if ( stringsCopied_ )
            return;

        stringSaver_.reset( new StringSaver<wchar_t>() );
        lpApplicationName = store( lpApplicationName );
        lpCommandLine = store( lpCommandLine );
        lpCurrentDirectory = store( lpCurrentDirectory );
        startupInfo.saveInfo( *stringSaver_ );
        stringsCopied_ = true;
    }

    wchar_t * widen( char const * str )
    {
        if ( !str )
            return NULL;
        return stringSaver_->save( converter_.from_bytes( str ).c_str() );
    }

    wchar_t * store( wchar_t const * str )
    {
        if ( !str )
            return NULL;
        return stringSaver_->save( str );
    }
};

class DistributedCompilation
{
    std::deque<std::vector<unsigned char> > stringSaver_;

    HANDLE eventHandle_;
    char const * compilerToolset_;
    char const * compilerExecutable_;
    FallbackFunction fallback_;
    std::unique_ptr<CreateProcessParams> cpParams_;
    bool completed_;
    DWORD exitCode_;

private:
    // Noncopyable
    DistributedCompilation( DistributedCompilation const & );
    DistributedCompilation operator=( DistributedCompilation const & );
    DistributedCompilation( DistributedCompilation && );
    DistributedCompilation operator=( DistributedCompilation && );

    static int fallbackFunction( char const * /*reason*/, void * params )
    {
        DistributedCompilation * pdcp = (DistributedCompilation *)params;
        return pdcp->fallback();
    }

    int fallback()
    {
        PROCESS_INFORMATION processInfo;
        BOOL const cpResult = CreateProcessW(
            cpParams_->lpApplicationName,
            cpParams_->lpCommandLine,
            cpParams_->lpProcessAttributes,
            cpParams_->lpThreadAttributes,
            TRUE,
            cpParams_->dwCreationFlags,
            cpParams_->environment.createEnvBlock(),
            cpParams_->lpCurrentDirectory,
            reinterpret_cast<LPSTARTUPINFOW>( &cpParams_->startupInfo ),
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

    static DWORD WINAPI distributedCompileWorker( void * params )
    {
        DistributedCompilation * pdcp = (DistributedCompilation *)params;
        return pdcp->distributedCompile();
    }

    DWORD distributedCompile()
    {
        WideConverter converter;
        std::string const commandLine( converter.to_bytes( cpParams_->lpCommandLine ) );
        std::string const currentPath( converter.to_bytes( cpParams_->lpCurrentDirectory ) );

        HookProcessAPIHooks::Data & hookData( HookProcessAPIHooks::getData() );
        int result = ::distributedCompile(
            compilerToolset_,
            compilerExecutable_,
            cpParams_->environment,
            commandLine.c_str(),
            currentPath.c_str(),
            hookData.portName.c_str(),
            fallbackFunction,
            this,
            cpParams_->startupInfo.hStdOutput,
            cpParams_->startupInfo.hStdError
        );
        {
            std::unique_lock<std::recursive_mutex> lock( hookData.mutex );
            if ( !complete( (DWORD)result ) )
                return 0;
        }
        SetEvent( eventHandle_ );
        return 0;
    }

public:
    DistributedCompilation
    (
        HANDLE eventHandle,
        char const * compilerToolset,
        char const * compilerExecutable,
        CreateProcessParams const & cpParams
    )
        :
        eventHandle_( eventHandle ),
        compilerToolset_( compilerToolset ),
        compilerExecutable_( compilerExecutable ),
        cpParams_( new CreateProcessParams( cpParams ) ), 
        completed_( false ),
        exitCode_( 0 )
    {
        cpParams_->saveInfo();
    }

    bool complete( DWORD exitCode )
    {
        if ( completed_ )
            return false;
        cpParams_.reset();
        completed_ = true;
        exitCode_ = (DWORD)exitCode;
        return true;
    }

    bool completed() const { return completed_; }
    DWORD exitCode() const { return exitCode_; }

    void startThread( LPPROCESS_INFORMATION lpProcessInformation, bool const suspended )
    {
        // When faking process id - use a ridiculously large number.
        lpProcessInformation->dwProcessId = 0x80000000 | ( (DWORD)eventHandle_ >> 1 );

        lpProcessInformation->hThread = CreateThread(
            NULL,
            64 * 1024,
            &distributedCompileWorker,
            this,
            suspended ? CREATE_SUSPENDED : 0,
            &lpProcessInformation->dwThreadId
        );
        lpProcessInformation->hProcess = eventHandle_;
    }
};

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

    
    HookProcessAPIHookDesc::Data const & hookData( HookProcessAPIHooks::getData() );
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
    HookProcessAPIHookDesc::Data & hookData( HookProcessAPIHooks::getData() );
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

bool shortCircuit
(
    CreateProcessParams const & createProcessParams,
    LPPROCESS_INFORMATION lpProcessInformation
)
{
    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    FileStatus fileStatus;
    bool haveStatus = false;
    std::string args;
    if ( createProcessParams.lpApplicationName )
    {
        haveStatus = getFileStatus( convert.to_bytes(
            createProcessParams.lpApplicationName ), fileStatus );
    }
    else
    {
        int argc;
        wchar_t * * argv = CommandLineToArgvW(
            createProcessParams.lpCommandLine, &argc );
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

    // Use an event handle to fake process handle to avoid hooking WFSO/WFMO.
    HANDLE eventHandle = CreateEvent( NULL, TRUE, FALSE, NULL );

    DistributedCompilationPtr const pDcp(
        new DistributedCompilation(
            eventHandle,
            "msvc",
            compiler,
            createProcessParams
        )
    );

    {
        std::unique_lock<std::recursive_mutex> lock( hookData.mutex );
        hookData.distributedCompilationInfo.insert( std::make_pair( eventHandle, pDcp ) );
    }

    pDcp->startThread( lpProcessInformation, ( createProcessParams.dwCreationFlags & CREATE_SUSPENDED ) != 0 );
    return true;
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

BOOL WINAPI HookProcessAPIHookDesc::createProcessA(
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
    CreateProcessParams const cpParams( lpApplicationName, lpCommandLine,
        lpProcessAttributes, lpThreadAttributes, bInheritHandles,
        dwCreationFlags, lpEnvironment, lpCurrentDirectory,
        lpStartupInfo );

    if ( shortCircuit( cpParams, lpProcessInformation ) )
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

BOOL WINAPI HookProcessAPIHookDesc::createProcessW(
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
    CreateProcessParams const cpParams( lpApplicationName, lpCommandLine,
        lpProcessAttributes, lpThreadAttributes, bInheritHandles,
        dwCreationFlags, lpEnvironment, lpCurrentDirectory, lpStartupInfo );

    if ( shortCircuit( cpParams, lpProcessInformation ) )
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

BOOL WINAPI HookProcessAPIHookDesc::getExitCodeProcess( HANDLE hProcess, LPDWORD lpExitCode )
{
    {
        HookProcessAPIHooks::Data & hookData( HookProcessAPIHooks::getData() );
        std::unique_lock<std::recursive_mutex> lock( hookData.mutex );
        DistributedCompilationInfo::const_iterator const dcpIter = hookData.distributedCompilationInfo.find( hProcess );
        if ( dcpIter != hookData.distributedCompilationInfo.end() )
        {
            if ( !dcpIter->second->completed() )
                return STILL_ACTIVE;
            *lpExitCode = dcpIter->second->exitCode();
            return TRUE;
        }
    }
    return GetExitCodeProcess( hProcess, lpExitCode );
}

BOOL WINAPI HookProcessAPIHookDesc::closeHandle( HANDLE handle )
{
    {
        HookProcessAPIHooks::Data & hookData( HookProcessAPIHooks::getData() );
        std::unique_lock<std::recursive_mutex> lock( hookData.mutex );
        DistributedCompilationInfo::const_iterator const dcpIter = hookData.distributedCompilationInfo.find( handle );
        if ( dcpIter != hookData.distributedCompilationInfo.end() )
            hookData.distributedCompilationInfo.erase( dcpIter );
    }
    return CloseHandle( handle );
}

BOOL WINAPI HookProcessAPIHookDesc::terminateProcess( HANDLE handle, UINT uExitCode )
{
    {
        HookProcessAPIHooks::Data & hookData( HookProcessAPIHooks::getData() );
        std::unique_lock<std::recursive_mutex> lock( hookData.mutex );
        DistributedCompilationInfo::iterator const dcpIter = hookData.distributedCompilationInfo.find( handle );
        if ( dcpIter != hookData.distributedCompilationInfo.end() )
        {
            dcpIter->second->complete( uExitCode );
            lock.unlock();
            SetEvent( handle );
            return TRUE;
        }
    }
    return TerminateProcess( handle, uExitCode );
}

VOID WINAPI HookProcessAPIHookDesc::exitProcess( UINT uExitCode )
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
