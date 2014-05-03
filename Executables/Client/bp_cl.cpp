#include "client.hpp"

#include <chrono>
#include <codecvt>
#include <iostream>
#include <windows.h>

char const compilerToolset[] = "msvc";
unsigned int compilerToolsetSize = sizeof(compilerToolset) / sizeof(compilerToolset[0]) - 1;
char const defaultPortName[] = "default";
unsigned int defaultPortNameSize = sizeof(defaultPortName) / sizeof(defaultPortName[0]);

char const compilerExeFilename[] = "cl.exe";
std::size_t compilerExeFilenameSize = sizeof(compilerExeFilename) / sizeof(compilerExeFilename[0]) - 1;

#ifdef __GNUC__
#define alloca __builtin_alloca
#endif

int runLocallyFallback()
{
    std::cout << "Running command locally...\n";
    wchar_t const * commandLine = GetCommandLineW();
    wchar_t const * argsPos = findArgs( commandLine );
    std::size_t const argsLen = wcslen( argsPos );
    std::size_t const commandLineSize = sizeof(compilerExeFilename) - 1 + argsLen;

    // Create a copy on the stack as required by CreateProcess.
    std::size_t pos( 0 );
    wchar_t * const buffer = static_cast<wchar_t *>( alloca( ( commandLineSize + 1 ) * sizeof(wchar_t) ) );
    std::memcpy( buffer, compilerExeFilename, ( sizeof(compilerExeFilename) - 1 ) * sizeof(wchar_t) );
    pos += compilerExeFilenameSize;
    std::memcpy( buffer + pos, argsPos, argsLen );
    buffer[ commandLineSize ] = 0;

    return createProcess( buffer );
}

struct Timer
{
    Timer() : start_( std::chrono::high_resolution_clock::now() ) {}
    ~Timer()
    {
        typedef std::chrono::duration<float, std::chrono::seconds::period> Duration;
        Duration ds( std::chrono::high_resolution_clock::now() - start_ );
        std::cout << "Command took " << ds.count() << " seconds.\n";
    }

    std::chrono::high_resolution_clock::time_point start_;
};

int main()
{
    Timer t;
    std::string compilerExecutable;
    if ( !findOnPath( getPath(), compilerExeFilename, compilerExecutable ) )
    {
        std::cerr << "Failed to locate executable 'cl.exe' on PATH.\n";
        return -1;
    }

    bool disableFallback = false;
    {
        DWORD size = GetEnvironmentVariable( "BP_DISABLE_FALLBACK", NULL, 0 );
        disableFallback = ( size != 0 ) || ( GetLastError() != ERROR_ENVVAR_NOT_FOUND );
    }

    DWORD size = GetEnvironmentVariable("BP_MANAGER_PORT", NULL, 0 );
    char const * portName;
    if ( size == 0 )
    {
        portName = defaultPortName;
        size = defaultPortNameSize;
    }
    else if ( size > 256 )
    {
        std::cerr << "Invalid BP_MANAGER_PORT environment variable value (value too big).\n";
        return disableFallback ? -1 : runLocallyFallback();
    }
    else
    {
        char * tmp = static_cast<char *>( alloca( size ) );
        GetEnvironmentVariable( "BP_MANAGER_PORT", tmp, size );
        portName = tmp;
    }

    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
    return distributedCompile(
        "msvc",
        compilerExecutable,
        GetCommandLineW(),
        llvm::StringRef( portName, size ),
        disableFallback ? NULL : runLocallyFallback
    );
}