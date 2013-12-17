//----------------------------------------------------------------------------
#include "DLLInject.hpp"
#include "remoteOps.hpp"

#include <cassert>
#include <Windows.h>

DLLInjector::DLLInjector( DWORD const processId, HMODULE module )
	:
	processHandle_( ::OpenProcess( PROCESS_ALL_ACCESS, false, processId ) ),
    localModuleHandle_( module )
{
    assert( processHandle_ );
    bool const result = injectLibrary( module );
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


bool DLLInjector::injectLibrary( HMODULE hModule )
{
    char moduleFileName[ MAX_PATH ];
    DWORD size = GetModuleFileName( hModule, moduleFileName, MAX_PATH );
    assert( size < MAX_PATH );
	void * remoteDllName = ::VirtualAllocEx( processHandle_, NULL, size, MEM_COMMIT, PAGE_READWRITE );
	if ( remoteDllName == NULL )
		return false;
	SIZE_T count;
	::WriteProcessMemory( processHandle_, remoteDllName, moduleFileName, size, &count );
	if ( count != size )
		return false;
	loadLibrary( remoteDllName );
	::VirtualFreeEx( processHandle_, remoteDllName, size, MEM_DECOMMIT );
    return true;
}


void DLLInjector::loadLibrary( void * dllName )
{
	DWORD remoteThreadExitCode;
	assert( dllName != 0 );
	PTHREAD_START_ROUTINE pLoadLibraryA = (PTHREAD_START_ROUTINE) GetProcAddress( GetModuleHandle(TEXT("Kernel32")), "LoadLibraryA" );
	HANDLE loadLibraryThread = CreateRemoteThread( processHandle_, NULL, 0, pLoadLibraryA, dllName, 0, NULL );
	::WaitForSingleObject( loadLibraryThread, INFINITE );
	::GetExitCodeThread( loadLibraryThread, &remoteThreadExitCode );
	::CloseHandle( loadLibraryThread );
    assert( remoteThreadExitCode != 0 );
	moduleHandle_ = (HMODULE)remoteThreadExitCode;
}


//----------------------------------------------------------------------------
