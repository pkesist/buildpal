//----------------------------------------------------------------------------
#pragma once
//----------------------------------------------------------------------------
#ifndef dllInject_HPP__1955D571_E264_4806_8F8A_046574F683C7
#define dllInject_HPP__1955D571_E264_4806_8F8A_046574F683C7
//----------------------------------------------------------------------------
#include <string>
#include <windows.h>

class DLLInjector
{
public:
	explicit DLLInjector( DWORD const processId, HMODULE module );
    ~DLLInjector();

    DWORD callRemoteProc( char const * const func, void * arg );

private:
    bool injectLibrary( HMODULE );
	void loadLibrary( void * dllName );

private:
	HANDLE processHandle_;
	HMODULE moduleHandle_;
	HMODULE localModuleHandle_;
};


//----------------------------------------------------------------------------
#endif
//----------------------------------------------------------------------------
