#include "client.hpp"
#include "hookProcess.hpp"

#include <cstdint>

#include <windows.h>

#ifdef _WIN64
char const vsRegKey[] = "Software\\Wow6432Node\\Microsoft\\VisualStudio\\";
#else
char const vsRegKey[] = "Software\\Microsoft\\VisualStudio\\";
#endif

char const * vsVersions[] = {
    "8.0\\Setup\\VC",
    "9.0\\Setup\\VC",
    "10.0\\Setup\\VC",
    "11.0\\Setup\\VC"
};

char const * compilerDirs[] = {
    "bin",
    "bin\\amd64",
    "bin\\x86_amd64",
    "bin\\x86_ia64",
};



typedef std::vector<std::string> CompilerList;

CompilerList detectCompilers()
{
    CompilerList result;
    for ( unsigned int index( 0 ); index < sizeof(vsVersions) / sizeof(vsVersions[0]); ++index)
    {
        std::string key = vsRegKey;
        key.append( vsVersions[ index ] );
        char vcPath[ MAX_PATH ];
        DWORD vcPathLen = MAX_PATH;
        HKEY vsKey;
        if
        (
            ( RegOpenKeyEx( HKEY_LOCAL_MACHINE, key.data(), 0, KEY_QUERY_VALUE, &vsKey ) == ERROR_SUCCESS ) &&
            ( RegQueryValueExA( vsKey, "ProductDir", 0, 0, (BYTE *)vcPath, &vcPathLen ) == ERROR_SUCCESS )
        )
        {
            
            for ( unsigned compilerDirIndex( 0 ); compilerDirIndex < sizeof(compilerDirs) / sizeof(compilerDirs[0]); ++compilerDirIndex)
            {
                std::string compilerPath( vcPath, vcPathLen - 1 );
                compilerPath.append( compilerDirs[ compilerDirIndex ] );
                compilerPath.append( "\\cl.exe" );
                DWORD const attributes = GetFileAttributes( compilerPath.c_str() );
                if ( attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY) )
                    result.push_back( compilerPath );
            }
        }
    }
    return result;
}


wchar_t * findArgs( wchar_t * cmdLine )
{
    bool inQuote = false;
    bool foundNonSpace = false;
    bool escape = false;

    for ( ; ; ++cmdLine )
    {
        switch ( *cmdLine )
        {
        case L' ':
        case L'\t':
        case L'\0': // In case there are no arguments.
            if ( foundNonSpace && !inQuote )
                while ( ( *cmdLine == L' ' ) || ( *cmdLine == L'\t' ) )
                    ++cmdLine;
                return cmdLine;
            escape = false;
            break;
        case L'\\':
            escape = !escape;
            break;
        case '"':
            foundNonSpace = true;
            if ( inQuote && !escape )
                inQuote = false;
            else if ( !inQuote )
                inQuote = true;
            break;
        default:
            foundNonSpace = true;
            escape = false;
        }
    }
}

int main()
{
    CompilerList const compilers( detectCompilers() );
    for ( std::string const & compiler : compilers )
        registerCompiler( compiler.c_str() );
    setPortName( "default" );

    STARTUPINFOW startupInfo = { sizeof(startupInfo) };
    PROCESS_INFORMATION procInfo = {};
    BOOL createSuccess = CreateProcessW
    (
        NULL,
        findArgs( GetCommandLineW() ),
        NULL,
        NULL,
        FALSE,
        0,
        NULL,
        NULL,
        &startupInfo,
        &procInfo
    );

    if ( !createSuccess )
        return -2;

    WaitForSingleObject( procInfo.hProcess, INFINITE );
    std::int32_t result;
    GetExitCodeProcess( procInfo.hProcess, (DWORD *)&result );
    CloseHandle( procInfo.hThread );
    CloseHandle( procInfo.hProcess );
    return result;
}