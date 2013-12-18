//----------------------------------------------------------------------------
#include "DLLInject.hpp"
#include "remoteOps.hpp"

#include <cassert>
#include <Windows.h>

bool const isCurrentProcess64Bit = sizeof(void *) == 8;

DLLInjector::DLLInjector( DWORD const processId )
	:
	processHandle_( ::OpenProcess( PROCESS_ALL_ACCESS, false, processId ) )
{
    assert( processHandle_ );
    bool const result = injectLibrary();
    assert( result );
    assert( moduleHandle_ );
}


DWORD DLLInjector::callRemoteProc( char const * const func, void * arg )
{
    LPTHREAD_START_ROUTINE const remote =
        (LPTHREAD_START_ROUTINE)GetRemoteProcAddress(
        processHandle_, moduleHandle_, func );
    assert( remote );
	HANDLE callRemoteProcThread = CreateRemoteThread( processHandle_, NULL,
        16 * 1024, remote, arg, 0, NULL );
	::WaitForSingleObject( callRemoteProcThread, INFINITE );
	DWORD remoteThreadExitCode;
	::GetExitCodeThread( callRemoteProcThread, &remoteThreadExitCode );
	::CloseHandle( callRemoteProcThread );
    return remoteThreadExitCode;
}


DLLInjector::~DLLInjector()
{
    CloseHandle( processHandle_ );
}


bool DLLInjector::injectLibrary()
{
    char const inject32bit[] = "map_files_inj32.dll";
    char const inject64bit[] = "map_files_inj64.dll";

    // We use the fact that one of these modules is loaded in the current
    // process.
    HMODULE currentLoaded;
    BOOL result = GetModuleHandleEx( GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        isCurrentProcess64Bit ? inject64bit : inject32bit,
        &currentLoaded );
    assert( result );
    char moduleToLoad[ MAX_PATH ];
    DWORD const moduleNameSize = GetModuleFileName( currentLoaded, moduleToLoad, MAX_PATH );

    bool on64BitOS;
    if ( isCurrentProcess64Bit )
        on64BitOS = true;
    else
    {
        BOOL isThis64bitOs;
        BOOL result = IsWow64Process( GetCurrentProcess(), &isThis64bitOs );
        assert( result );
        on64BitOS = isThis64bitOs != 0;
    }

    bool targetProcessIs64bit = false;
    if ( on64BitOS )
    {
        BOOL isWow64Process;
        BOOL result = IsWow64Process( processHandle_, &isWow64Process );
        assert( result );
        targetProcessIs64bit = !isWow64Process;
    }

    if ( targetProcessIs64bit != isCurrentProcess64Bit )
    {
        assert( moduleNameSize >= sizeof(inject32bit) );
        if ( targetProcessIs64bit )
        {
            moduleToLoad[ moduleNameSize - 6 ] = '6';
            moduleToLoad[ moduleNameSize - 5 ] = '4';
        }
        else
        {
            moduleToLoad[ moduleNameSize - 6 ] = '3';
            moduleToLoad[ moduleNameSize - 5 ] = '2';
        }
    }

	void * remoteDllName = ::VirtualAllocEx( processHandle_, NULL, moduleNameSize, MEM_COMMIT, PAGE_READWRITE );
	if ( remoteDllName == NULL )
		return false;
	SIZE_T count;
	::WriteProcessMemory( processHandle_, remoteDllName, moduleToLoad, moduleNameSize, &count );
	if ( count != moduleNameSize )
		return false;
	loadLibrary( remoteDllName );
	::VirtualFreeEx( processHandle_, remoteDllName, moduleNameSize, MEM_DECOMMIT );
    return true;
}


void DLLInjector::loadLibrary( void * dllName )
{
	DWORD remoteThreadExitCode;
	assert( dllName != 0 );
	PTHREAD_START_ROUTINE pLoadLibraryA = (PTHREAD_START_ROUTINE) GetProcAddress( GetModuleHandle( "Kernel32" ), "LoadLibraryA" );
	HANDLE loadLibraryThread = CreateRemoteThread( processHandle_, NULL, 0, pLoadLibraryA, dllName, 0, NULL );
	::WaitForSingleObject( loadLibraryThread, INFINITE );
	::GetExitCodeThread( loadLibraryThread, &remoteThreadExitCode );
	::CloseHandle( loadLibraryThread );
    assert( remoteThreadExitCode != 0 );
	moduleHandle_ = (HMODULE)remoteThreadExitCode;
}


//----------------------------------------------------------------------------
