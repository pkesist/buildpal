#include "client.hpp"

#include <llvm/Support/Process.h>

#include <chrono>
#include <codecvt>
#include <iostream>
#include <windows.h>

char const defaultPortName[] = "default";
char const compilerExeFilename[] = "cl.exe";

#ifdef __GNUC__
#define alloca __builtin_alloca
#endif

int runLocallyFallback( void * vpCompilerExe )
{
    char const * compilerExecutable = static_cast<char const *>( vpCompilerExe );
    std::cout << "Running command locally...\n";
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
    Timer t;
    Environment env;
    std::string compilerExecutable;
    if ( !findOnPath( getPath( env ), compilerExeFilename, compilerExecutable ) )
    {
        std::cerr << "Failed to locate executable 'cl.exe' on PATH.\n";
        return -1;
    }

    bool const disableFallback = !!env.get( "BP_DISABLE_FALLBACK" );
    llvm::Optional<std::string> portNameVar( env.get( "BP_MANAGER_PORT" ) );
    llvm::StringRef portName;
    if ( !portNameVar )
    {
        portName = llvm::StringRef( defaultPortName );
    }
    else
    {
        portName = llvm::StringRef( portNameVar->data(), portNameVar->size() );
    }

    std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;

    return distributedCompile(
        "msvc",
        compilerExecutable,
        env,
        GetCommandLineW(),
        portName,
        disableFallback ? NULL : runLocallyFallback,
        const_cast<char *>( compilerExecutable.c_str() )
    );
}