#include "remoteOps.hpp"

#include <cassert>
#include <string>
#include <vector>

#include <windows.h>
#include <psapi.h>

//-----------------------------------------------------------------------------

HMODULE WINAPI GetRemoteModuleHandle( HANDLE hProcess, char const * moduleName )
{
    assert( moduleName );
    std::vector<HMODULE> moduleArray( 100 );
 
    BOOL result;
    DWORD bytesNeeded;
    /* Get handles to all the modules in the target process */
    result = ::EnumProcessModulesEx(hProcess, &moduleArray[ 0 ],
        moduleArray.size() * sizeof(HMODULE), &bytesNeeded, LIST_MODULES_ALL );
    assert( result );
 
    /* We want the number of modules not the number of bytes */
    DWORD numModules = bytesNeeded / sizeof(HMODULE);
 
    /* Did we allocate enough memory for all the module handles? */
    if( numModules > moduleArray.size() )
    {
        moduleArray.resize( numModules );

        /* Get handles to all the modules in the target process */
        result = EnumProcessModulesEx(hProcess, &moduleArray[ 0 ],
            moduleArray.size() * sizeof(HMODULE), &bytesNeeded, LIST_MODULES_ALL );
        assert( result );
        assert( bytesNeeded == moduleArray.size() * sizeof(HMODULE) );
    }
 
    /* Iterate through all the modules and see if the names match the one we are looking for */
    for( std::size_t i = 0; i <= moduleArray.size(); ++i )
    {
        char moduleNameBuffer[ MAX_PATH ];
        /* Get the module's name */
        ::GetModuleBaseName(hProcess, moduleArray[i], moduleNameBuffer,
            sizeof(moduleNameBuffer));
 
        /* Does the name match? */
        if ( _stricmp( moduleNameBuffer, moduleName ) == 0 )
            return moduleArray[i];
    }
    return NULL;
}
 

//-----------------------------------------------------------------------------

PROC WINAPI GetRemoteProcAddress(
    HANDLE hProcess,
    HMODULE hModule,
    char const * lpProcName,
    unsigned int ordinal,
    bool useOrdinal
)
{
    BOOL result;
    assert( lpProcName != 0 || useOrdinal );
 
    /* Get the base address of the remote module along with some other info we don't need */
    MODULEINFO remoteModuleInfo = { 0 };
    result = ::GetModuleInformation(
        hProcess,
        hModule,
        &remoteModuleInfo, sizeof(remoteModuleInfo));
    assert( result );
    BYTE const * remoteModuleBaseVA = static_cast<BYTE const *>( remoteModuleInfo.lpBaseOfDll );
 
    /* Read the DOS header and check it's magic number */
    IMAGE_DOS_HEADER dosHeader = { 0 };
    result = ::ReadProcessMemory( hProcess, remoteModuleBaseVA, &dosHeader,
        sizeof(IMAGE_DOS_HEADER), NULL);
    assert( result );
    assert( dosHeader.e_magic == IMAGE_DOS_SIGNATURE );
 
    /* Read and check the NT signature */
    DWORD signature = 0;
    result = ::ReadProcessMemory( hProcess, remoteModuleBaseVA + dosHeader.e_lfanew,
        &signature, sizeof(DWORD), NULL );
    assert( result );
    assert( signature == IMAGE_NT_SIGNATURE );
    
    /* Read the main header */
    IMAGE_FILE_HEADER fileHeader = { 0 };
    result = ::ReadProcessMemory(hProcess,
        (remoteModuleBaseVA + dosHeader.e_lfanew + sizeof(DWORD)),
        &fileHeader,
        sizeof(IMAGE_FILE_HEADER),
        NULL);
    assert( result );
 
    assert( fileHeader.SizeOfOptionalHeader == sizeof(IMAGE_OPTIONAL_HEADER32) ||
        fileHeader.SizeOfOptionalHeader == sizeof(IMAGE_OPTIONAL_HEADER64));

    bool const is64 = fileHeader.SizeOfOptionalHeader == sizeof(IMAGE_OPTIONAL_HEADER64);

    IMAGE_DATA_DIRECTORY exportDirectory = {0};
    if ( is64 )
    {
        IMAGE_OPTIONAL_HEADER64 optHeader64 = { 0 };

        /* Read the optional header and check it's magic number */
        result = ::ReadProcessMemory(hProcess,
            (remoteModuleBaseVA + dosHeader.e_lfanew + sizeof(DWORD) + sizeof(IMAGE_FILE_HEADER)),
            &optHeader64, sizeof(IMAGE_OPTIONAL_HEADER64), NULL);
        assert( result );
        assert( optHeader64.Magic == IMAGE_NT_OPTIONAL_HDR64_MAGIC );
        assert( optHeader64.NumberOfRvaAndSizes >= IMAGE_DIRECTORY_ENTRY_EXPORT + 1 );
        exportDirectory.VirtualAddress = (optHeader64.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT]).VirtualAddress;
        exportDirectory.Size = (optHeader64.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT]).Size;
    }
    else
    {
        IMAGE_OPTIONAL_HEADER32 optHeader32 = { 0 };
        result = ::ReadProcessMemory(hProcess,
            (remoteModuleBaseVA + dosHeader.e_lfanew + sizeof(DWORD) + sizeof(IMAGE_FILE_HEADER)),
            &optHeader32, sizeof(IMAGE_OPTIONAL_HEADER32), NULL);
        assert( result );
        assert( optHeader32.Magic == IMAGE_NT_OPTIONAL_HDR32_MAGIC );
        assert( optHeader32.NumberOfRvaAndSizes >= IMAGE_DIRECTORY_ENTRY_EXPORT + 1 );
        exportDirectory.VirtualAddress = (optHeader32.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT]).VirtualAddress;
        exportDirectory.Size = (optHeader32.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT]).Size;
    }

    /* Read the main export table */
    IMAGE_EXPORT_DIRECTORY exportTable = {0};
    result = ::ReadProcessMemory( hProcess,
        (remoteModuleBaseVA + exportDirectory.VirtualAddress),
        &exportTable, sizeof(IMAGE_EXPORT_DIRECTORY), NULL);
    assert( result );
 
    /* Save the absolute address of the tables so we don't need to keep adding the base address */
    BYTE const * exportFunctionTableVA = remoteModuleBaseVA + exportTable.AddressOfFunctions;
    BYTE const * exportNameTableVA = remoteModuleBaseVA + exportTable.AddressOfNames;
    BYTE const * exportOrdinalTableVA = remoteModuleBaseVA + exportTable.AddressOfNameOrdinals;
 
    /* Allocate memory for our copy of the tables */
    std::vector<DWORD> exportFunctionTable( exportTable.NumberOfFunctions );
    std::vector<DWORD> exportNameTable( exportTable.NumberOfNames );
    std::vector<WORD> exportOrdinalTable( exportTable.NumberOfNames );
 
    /* Get a copy of the function table */
    result = ::ReadProcessMemory( hProcess, exportFunctionTableVA,
        &exportFunctionTable[0],
        exportFunctionTable.size() * sizeof(DWORD), NULL);
    assert( result );
 
    /* Get a copy of the name table */
    result = ::ReadProcessMemory( hProcess, exportNameTableVA,
        &exportNameTable[0],
        exportNameTable.size() * sizeof(DWORD), NULL);
    assert( result );
 
    /* Get a copy of the ordinal table */
    result = ::ReadProcessMemory( hProcess, exportOrdinalTableVA,
        &exportOrdinalTable[0],
        exportOrdinalTable.size() * sizeof(WORD), NULL);
    assert( result );
 
    if ( useOrdinal )
    {
        ordinal -= exportTable.Base;
    }
    else
    {
        // Iterate through all the names and see if they match the one we are looking for
        bool found = false;
        for( unsigned int i = 0; i < exportNameTable.size(); ++i )
        {
            std::string tempFunctionName;
 
            // Get the function name one character at a time because we don't know how long it is
            char tmpChar = 1;
            for( unsigned int j = 0; tmpChar != 0; ++j )
            {
                // Get next character
                result = ::ReadProcessMemory( hProcess,
                    ( remoteModuleBaseVA + exportNameTable[i] + j ),
                    &tmpChar,
                    sizeof(char),
                    NULL);
                assert( result );
 
                tempFunctionName.push_back( tmpChar );
            }
 
            // Does the name match?
            if( _stricmp( lpProcName, tempFunctionName.c_str() ) == 0 )
            {
                ordinal = exportOrdinalTable[i];
                found = true;
                break;
            }
        }
        if ( !found )
            return NULL;
    }
    
    unsigned int const funcOffset = exportFunctionTable[ ordinal ];
    // If the function is not forwarded we are done
    if( funcOffset < exportDirectory.VirtualAddress ||
        funcOffset > exportDirectory.VirtualAddress + exportDirectory.Size)
        return (PROC)( remoteModuleBaseVA + funcOffset );

    std::string tempForwardString;

    /* Get the forwarder string one character at a time because we don't know how long it is */
    char tmpChar = 1;
    for( unsigned int i = 0; tmpChar != '\0'; ++i )
    {
        result = ::ReadProcessMemory(hProcess,
            ( remoteModuleBaseVA + funcOffset + i ),
            &tmpChar, sizeof(tmpChar), NULL);
        assert( result );
 
        tempForwardString.push_back( tmpChar ); // Add it to the string
    }
 
    /* Find the dot that seperates the module name and the function name/ordinal */
    size_t const dotPos = tempForwardString.find('.');
    assert( dotPos != std::string::npos );
 
    /* Temporary variables that hold parts of the forwarder string */
    std::string const realModuleName = tempForwardString.substr( 0, dotPos - 1 );
    std::string const realFunctionId = tempForwardString.substr( dotPos + 1 );
 
    HMODULE const realModule = GetRemoteModuleHandle( hProcess, realModuleName.c_str() );

    /* Figure out if the function was exported by name or by ordinal */
    if( realFunctionId[ 0 ] == '#' ) // Exported by ordinal
        return GetRemoteProcAddress( hProcess, realModule, NULL, atoi( realFunctionId.c_str() + 1 ), true );
    return GetRemoteProcAddress( hProcess, realModule, realFunctionId.c_str(), 0, false );
}
 
//-----------------------------------------------------------------------------