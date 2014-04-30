#include "client.hpp"

#include <chrono>
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

char const * findArgs( char const * cmdLine )
{
    bool inQuote = false;
    bool foundNonSpace = false;
    bool escape = false;

    for ( ; ; ++cmdLine )
    {
        switch ( *cmdLine )
        {
        case ' ':
        case '\t':
        case '\0': // In case there are no arguments.
            if ( foundNonSpace && !inQuote )
                return cmdLine;
            escape = false;
            break;
        case '\\':
            escape = !escape;
            break;
        case '"':
            if ( inQuote && !escape )
                inQuote = false;
            break;
        default:
            foundNonSpace = true;
            escape = false;
        }
    }
}

int runLocallyFallback()
{
    std::cout << "Running command locally...\n";
    char const * commandLine = GetCommandLine();
    char const * argsPos = findArgs( commandLine );
    std::size_t const argsLen = strlen( argsPos );
    std::size_t const commandLineSize = sizeof(compilerExeFilename) - 1 + argsLen;

    // Create a copy on the stack as required by CreateProcess.
    std::size_t pos( 0 );
    char * const buffer = static_cast<char *>( alloca( commandLineSize + 1 ) );
    std::memcpy( buffer, compilerExeFilename, sizeof(compilerExeFilename) - 1 );
    pos += sizeof(compilerExeFilename) - 1;
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

int main( int argc, char * argv[] )
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

    return distributedCompile(
        llvm::StringRef( compilerToolset, compilerToolsetSize ),
        compilerExecutable,
        argc, argv,
        llvm::StringRef( portName, size ),
        disableFallback ? NULL : runLocallyFallback
    );
}