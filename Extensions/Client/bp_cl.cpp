#include "../../Extensions/Client/client.hpp"

#include <llvm/Support/Process.h>

#include <chrono>
#include <codecvt>
#include <iostream>
#include <windows.h>

int runLocallyFallback( char const * reason, void * vpCompilerExe )
{
    char const * compilerExecutable = static_cast<char const *>( vpCompilerExe );
    std::cerr
        << "ERROR: " << reason << "\nRunning command locally...\n";
    return createProcess( compilerExecutable, GetCommandLineA() );
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
    //Timer t;
    Environment env( GetEnvironmentStringsA(), false );

    std::string compilerExecutable;
    PathList pathList;
    getPath( env, pathList );
    if ( !findOnPath( pathList, "cl.exe", compilerExecutable ) )
    {
        std::cerr << "Failed to locate executable 'cl.exe' on PATH.\n";
        return -1;
    }

    bool const disableFallback = !!env.get( "BP_DISABLE_FALLBACK" );
    llvm::Optional<std::string> const portNameVar( env.get( "BP_MANAGER_PORT" ) );

    return distributedCompile(
        "msvc",
        compilerExecutable.c_str(),
        env,
        GetCommandLineA(),
        NULL,
        portNameVar ? portNameVar->data() : "default",
        disableFallback ? NULL : runLocallyFallback,
        const_cast<char *>( compilerExecutable.c_str() )
    );
}