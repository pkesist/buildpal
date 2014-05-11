#include "client.hpp"
#include "hookProcess.hpp"

#include <cstdint>

#include <windows.h>

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
    STARTUPINFOW startupInfo = { sizeof(startupInfo) };
    PROCESS_INFORMATION procInfo = {};
    BOOL createSuccess = createProcessW
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