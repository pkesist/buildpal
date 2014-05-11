//----------------------------------------------------------------------------
#pragma once
//----------------------------------------------------------------------------
#ifndef dllInject_HPP__1955D571_E264_4806_8F8A_046574F683C7
#define dllInject_HPP__1955D571_E264_4806_8F8A_046574F683C7
//----------------------------------------------------------------------------
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>

bool injectLibrary(
    // process handle where to inject library
    void * processHandle,
    // filenames of DLL (32/64 bit) to inject
    // corresponding one must be loaded in the current process  to determine
    // the directory
    char const * dllNames[2],
    // initialization function to call in the DLL
    // signature must be DWORD (*)( void * );
    char const * initFunc,
    // arguments to pass to the initialization function
    // note that this data must be available in the target
    // process:
    //     if it is a handle, it should be duplicated for the target process
    //     via DuplicateHandle().
    //     if it is memory, it should be allocated in the target process
    //     via VirtualAllocEx().
    void * initArgs
);

DWORD hookWinAPI( PROC const * original, PROC const * replacement, unsigned int procCount );


//----------------------------------------------------------------------------
#endif
//----------------------------------------------------------------------------
