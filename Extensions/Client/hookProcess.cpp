#include "hookProcess.hpp"

#include "../../Extensions/Client/client.hpp"
#include "../../Extensions/Common/apiHooks.hpp"

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
#include <unordered_map>

#include <windows.h>
#include <shellapi.h>
#include <psapi.h>

typedef llvm::sys::fs::UniqueID FileStatus;
bool getFileStatus( llvm::StringRef path, FileStatus & result )
{
    return !llvm::sys::fs::getUniqueID( path, result );
}

struct CompilerDescription
{
    std::string compilerPath;
    std::string replacement;
};

struct CompilerExecutables
{
    typedef std::map<FileStatus, CompilerDescription> FileMap;
    FileMap files;

    void registerFile( llvm::StringRef compilerPath, llvm::StringRef replacement )
    {
        FileStatus fileStatus;
        CompilerDescription desc = { compilerPath.str(), replacement.str() };
        if ( getFileStatus( compilerPath, fileStatus ) )
            files.insert( std::make_pair( fileStatus, desc ) );
    }
};

class DistributedCompilation;
typedef std::shared_ptr<DistributedCompilation> DistributedCompilationPtr;
typedef std::map<HANDLE, DistributedCompilationPtr> DistributedCompilationInfo;

struct Mutex
{
    CRITICAL_SECTION criticalSection_;

    Mutex() { InitializeCriticalSection( &criticalSection_ ); }
    ~Mutex() { DeleteCriticalSection( &criticalSection_ ); }

    void lock() { EnterCriticalSection( &criticalSection_ ); }
    void unlock() { LeaveCriticalSection( &criticalSection_ ); }
};

class HookProcessAPIHookDesc
{
private:
    static BOOL WINAPI closeHandle( HANDLE );
    static BOOL WINAPI getExitCodeProcess( HANDLE hProcess, LPDWORD lpExitCode );
    static BOOL WINAPI terminateProcess( HANDLE hProcess, UINT uExitCode );

public:
    static char const moduleName[];
    static APIHookItem const items[]; 
    static unsigned int const itemsCount;
};

char const HookProcessAPIHookDesc::moduleName[] = "kernel32.dll";

APIHookItem const HookProcessAPIHookDesc::items[] = 
{
    { "CreateProcessA"    , (PROC)createProcessA     },
    { "CreateProcessW"    , (PROC)createProcessW     },
    { "GetExitCodeProcess", (PROC)getExitCodeProcess },
    { "CloseHandle"       , (PROC)closeHandle        },
    { "TerminateProcess"  , (PROC)terminateProcess   }
};

unsigned int const HookProcessAPIHookDesc::itemsCount = sizeof(items) / sizeof(items[0]);

struct HookProcessAPIHookData
{
    HookProcessAPIHookData() : portName( "default" ) {}

    CompilerExecutables compilers;
    std::string portName;
    DistributedCompilationInfo distributedCompilationInfo;
    Mutex mutex;
};

struct HookProcessAPIHooks : public APIHooks<HookProcessAPIHooks, HookProcessAPIHookData>
{
    HookProcessAPIHooks()
    {
        addAPIHook<HookProcessAPIHookDesc>();
    }
};

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

    StartupInfoEx( LPSTARTUPINFOW si, StringSaver<wchar_t> & saver )
    {
        static_cast<STARTUPINFOW &>( *this ) = *si;
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
        stringSaver_( new StringSaver<wchar_t>() ),
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
        postProcessArgs();
    }

    CreateProcessParams( wchar_t const * appName, wchar_t * commandLine,
        LPSECURITY_ATTRIBUTES procAttr, LPSECURITY_ATTRIBUTES threadAttr,
        BOOL inherit, DWORD flags, void * env, wchar_t const * curDir,
        LPSTARTUPINFOW pStartupInfo )
        :
        stringSaver_( new StringSaver<wchar_t>() ),
        savedInfo_( false ),
        stringsCopied_( false ),
        lpApplicationName( store( appName ) ),
        lpCommandLine( store( commandLine ) ),
        lpProcessAttributes( procAttr ),
        lpThreadAttributes( threadAttr ),
        bInheritHandles( inherit ),
        dwCreationFlags( flags ),
        environment( env, ( flags & CREATE_UNICODE_ENVIRONMENT ) != 0 ),
        lpCurrentDirectory( store( curDir ) ),
        startupInfo( pStartupInfo, *stringSaver_ )
    {
        postProcessArgs();
    }

    ~CreateProcessParams()
    {
        CloseHandle( startupInfo.hStdOutput );
        CloseHandle( startupInfo.hStdError );
    }


private:
    void postProcessArgs()
    {
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
            lpCurrentDirectory = store( curPath );
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

    std::shared_ptr<StringSaver<wchar_t> > stringSaver_;
    WideConverter converter_;

public:
    wchar_t const * lpApplicationName;
    wchar_t * lpCommandLine;
    LPSECURITY_ATTRIBUTES lpProcessAttributes;
    LPSECURITY_ATTRIBUTES lpThreadAttributes;
    BOOL bInheritHandles;
    DWORD dwCreationFlags;
    Environment environment;
    wchar_t const * lpCurrentDirectory;
    StartupInfoEx startupInfo;
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

        HookProcessAPIHookData & hookData( HookProcessAPIHooks::getData() );
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
            cpParams_->startupInfo.hStdError,
            HookProcessAPIHooks::original( (PROC)createProcessA )
        );
        {
            std::unique_lock<Mutex> lock( hookData.mutex );
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
        CreateProcessParams * cpParams
    )
        :
        eventHandle_( eventHandle ),
        compilerToolset_( compilerToolset ),
        compilerExecutable_( compilerExecutable ),
        cpParams_( cpParams ), 
        completed_( false ),
        exitCode_( 0 )
    {
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

bool hookProcess( HANDLE processHandle, HANDLE mainThread, bool resume )
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

    
    HookProcessAPIHookData const & hookData( HookProcessAPIHooks::getData() );
    CompilerExecutables::FileMap const & compilerFiles( hookData.compilers.files );

    for
    (
        CompilerExecutables::FileMap::const_iterator iter( compilerFiles.begin() );
        iter != compilerFiles.end();
        ++iter
    )
    {
        DWORD bytesWritten;
        WriteFile( pipeWrite, iter->second.compilerPath.c_str(), iter->second.compilerPath.size() + 1, &bytesWritten, NULL );
        assert( iter->second.compilerPath.size() + 1 == bytesWritten );
        WriteFile( pipeWrite, iter->second.replacement.c_str(), iter->second.replacement.size() + 1, &bytesWritten, NULL );
        assert( iter->second.replacement.size() + 1 == bytesWritten );
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

    return injectLibrary( processHandle, dllNames, initFunc, targetRead, NULL, NULL, mainThread, resume );
}

DWORD WINAPI Initialize( HANDLE pipeHandle, HANDLE initDone )
{
    bool readingPortName = false;
    bool readingReplacement = false;
    bool done = false;
    HookProcessAPIHookData & hookData( HookProcessAPIHooks::getData() );
    while ( !done )
    {
        char buffer[ 1024 ];
        DWORD last = 0;
        DWORD read;
        ReadFile( pipeHandle, buffer, 1024, &read, 0 );
        std::string remainder;
        std::string compilerPath;
        for ( DWORD index( 0 ); index < read; ++index )
        {
            if ( buffer[ index ] == '\0' )
            {
                if ( last == index )
                {
                    if ( !readingReplacement && !readingPortName )
                    {
                        last++;
                        readingPortName = true;
                        continue;
                    }
                }
                std::string const data = remainder + std::string( buffer + last, index - last );
                remainder.clear();
                if ( readingPortName )
                {
                    done = true;
                    hookData.portName = data;
                }
                else if ( readingReplacement )
                {
                    hookData.compilers.registerFile( compilerPath, data );
                    readingReplacement = false;
                }
                else
                {
                    compilerPath = data;
                    readingReplacement = true;
                }
                last = index + 1;
            }
        }
        remainder += std::string( buffer + last, read - last );
    }
    CloseHandle( pipeHandle );
    HookProcessAPIHooks::enable();
    if ( initDone )
    {
        SetEvent( initDone );
        WaitForSingleObject( initDone, INFINITE );
        CloseHandle( initDone );
    }
    return 0;
}

void enableHooks()
{
    HookProcessAPIHooks::enable();
}

void disableHooks()
{
    HookProcessAPIHooks::disable();
}


CompilerDescription const * isCompiler( wchar_t const * appName, wchar_t const * cmd )
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
        wchar_t * * argv = CommandLineToArgvW( cmd, &argc );
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

    CompilerDescription * compilerDesc = NULL;
    HookProcessAPIHookData & hookData( HookProcessAPIHooks::getData() );
    CompilerExecutables::FileMap::const_iterator const end = hookData.compilers.files.end();
    for
    (
        CompilerExecutables::FileMap::const_iterator iter = hookData.compilers.files.begin();
        iter != end;
        ++iter
    )
    {
        if ( iter->first == fileStatus )
        {
            return &iter->second;
        }
    }

    return NULL;
}

CompilerDescription const * isCompiler( char const * appName, char const * cmd )
{
    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    return isCompiler( appName ? convert.from_bytes( appName ).c_str() : NULL,
        cmd ? convert.from_bytes( cmd ).c_str() : NULL );
}

bool shortCircuit
(
    CreateProcessParams * cpParams,
    LPPROCESS_INFORMATION lpProcessInformation,
    std::string const & compilerPath,
    bool suspended
)
{
    // Use an event handle to fake process handle to avoid hooking WFSO/WFMO.
    HANDLE eventHandle = CreateEvent( NULL, TRUE, FALSE, NULL );

    DistributedCompilationPtr const pDcp(
        new DistributedCompilation(
            eventHandle,
            "msvc",
            compilerPath.c_str(),
            cpParams
        )
    );

    {
        HookProcessAPIHookData & hookData( HookProcessAPIHooks::getData() );
        std::unique_lock<Mutex> lock( hookData.mutex );
        hookData.distributedCompilationInfo.insert( std::make_pair( eventHandle, pDcp ) );
    }

    pDcp->startThread( lpProcessInformation, suspended );
    return true;
}

void registerCompiler( char const * compilerPath, char const * replacement )
{
    HookProcessAPIHookData & hookData( HookProcessAPIHooks::getData() );
    hookData.compilers.registerFile( compilerPath, replacement );
}

void setPortName( char const * portName )
{
    HookProcessAPIHookData & hookData( HookProcessAPIHooks::getData() );
    hookData.portName = portName;
}


template <typename FuncType>
FuncType getOriginal( FuncType func )
{
    return reinterpret_cast<FuncType>( HookProcessAPIHooks::original(
        reinterpret_cast<PROC>( func ) ) );
}

BOOL WINAPI createProcessA( CREATE_PROCESS_PARAMSA )
{
    static auto origCreateProcessA = getOriginal( createProcessA );

    CompilerDescription const * compilerDesc( isCompiler(
        lpApplicationName,
        lpCommandLine )
    );

    if ( compilerDesc )
    {
        if ( compilerDesc->replacement.empty() )
        {
            shortCircuit
            (
                new CreateProcessParams(
                    lpApplicationName, lpCommandLine, lpProcessAttributes,
                    lpThreadAttributes, bInheritHandles, dwCreationFlags,
                    lpEnvironment, lpCurrentDirectory, lpStartupInfo ),
                lpProcessInformation,
                compilerDesc->compilerPath,
                ( dwCreationFlags & CREATE_SUSPENDED ) != 0
            );
            return 1;
        }
        else
        {
            return origCreateProcessA( 
                compilerDesc->replacement.c_str(),
                lpCommandLine,
                lpProcessAttributes,
                lpThreadAttributes,
                bInheritHandles,
                dwCreationFlags,
                lpEnvironment,
                lpCurrentDirectory,
                lpStartupInfo,
                lpProcessInformation
            );
        }
    }
    
    bool const shouldResume = (dwCreationFlags & CREATE_SUSPENDED) == 0;
    BOOL result = origCreateProcessA( 
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
        hookProcess( lpProcessInformation->hProcess,
            lpProcessInformation->hThread, shouldResume );
    return result;
}

BOOL WINAPI createProcessW( CREATE_PROCESS_PARAMSW )
{
    static auto origCreateProcessW = getOriginal( createProcessW );

    CompilerDescription const * compilerDesc( isCompiler(
        lpApplicationName,
        lpCommandLine )
    );

    if ( compilerDesc )
    {
        if ( compilerDesc->replacement.empty() )
        {
            shortCircuit
            (
                new CreateProcessParams(
                    lpApplicationName, lpCommandLine, lpProcessAttributes,
                    lpThreadAttributes, bInheritHandles, dwCreationFlags,
                    lpEnvironment, lpCurrentDirectory, lpStartupInfo ),
                lpProcessInformation,
                compilerDesc->compilerPath,
                ( dwCreationFlags & CREATE_SUSPENDED ) != 0
            );
            return 1;
        }
        else
        {
            std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
            return origCreateProcessW( 
                convert.from_bytes( compilerDesc->replacement ).c_str(),
                lpCommandLine,
                lpProcessAttributes,
                lpThreadAttributes,
                bInheritHandles,
                dwCreationFlags,
                lpEnvironment,
                lpCurrentDirectory,
                lpStartupInfo,
                lpProcessInformation
            );
        }
    }
    
    bool const shouldResume = (dwCreationFlags & CREATE_SUSPENDED) == 0;
    BOOL result = origCreateProcessW( 
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
        hookProcess( lpProcessInformation->hProcess,
            lpProcessInformation->hThread, shouldResume );
    }
    return result;
}

BOOL WINAPI HookProcessAPIHookDesc::getExitCodeProcess( HANDLE hProcess, LPDWORD lpExitCode )
{
    static auto origGetExitCodeProcess = getOriginal( HookProcessAPIHookDesc::getExitCodeProcess );

    if ( HookProcessAPIHooks::isActive() )
    {
        HookProcessAPIHookData & hookData( HookProcessAPIHooks::getData() );
        std::unique_lock<Mutex> lock( hookData.mutex );
        DistributedCompilationInfo::const_iterator const dcpIter = hookData.distributedCompilationInfo.find( hProcess );
        if ( dcpIter != hookData.distributedCompilationInfo.end() )
        {
            if ( !dcpIter->second->completed() )
                return STILL_ACTIVE;
            *lpExitCode = dcpIter->second->exitCode();
            return TRUE;
        }
    }
    return origGetExitCodeProcess( hProcess, lpExitCode );
}

BOOL WINAPI HookProcessAPIHookDesc::closeHandle( HANDLE handle )
{
    static auto origCloseHandle = getOriginal( HookProcessAPIHookDesc::closeHandle );

    if ( HookProcessAPIHooks::isActive() )
    {
        HookProcessAPIHookData & hookData( HookProcessAPIHooks::getData() );
        std::unique_lock<Mutex> lock( hookData.mutex );
        DistributedCompilationInfo::const_iterator const dcpIter = hookData.distributedCompilationInfo.find( handle );
        if ( dcpIter != hookData.distributedCompilationInfo.end() )
            hookData.distributedCompilationInfo.erase( dcpIter );
    }
    return origCloseHandle( handle );
}

BOOL WINAPI HookProcessAPIHookDesc::terminateProcess( HANDLE handle, UINT uExitCode )
{
    static auto origTerminateProcess = getOriginal( HookProcessAPIHookDesc::terminateProcess );

    if ( HookProcessAPIHooks::isActive() )
    {
        HookProcessAPIHookData & hookData( HookProcessAPIHooks::getData() );
        std::unique_lock<Mutex> lock( hookData.mutex );
        DistributedCompilationInfo::iterator const dcpIter = hookData.distributedCompilationInfo.find( handle );
        if ( dcpIter != hookData.distributedCompilationInfo.end() )
        {
            dcpIter->second->complete( uExitCode );
            lock.unlock();
            SetEvent( handle );
            return TRUE;
        }
    }
    return origTerminateProcess( handle, uExitCode );
}
