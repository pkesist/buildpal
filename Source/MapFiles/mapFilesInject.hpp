//------------------------------------------------------------------------------
#ifndef mapFilesInject_HPP__A6FF475B_B11B_486F_B491_549FBAFAEA1A
#define mapFilesInject_HPP__A6FF475B_B11B_486F_B491_549FBAFAEA1A
//------------------------------------------------------------------------------
#include <Windows.h>
//------------------------------------------------------------------------------

extern "C" BOOL WINAPI addFileMapping( char const * virtualEntry, char const * realEntry );
extern "C" BOOL WINAPI removeFileMapping( char const * virtualEntry );
extern "C" BOOL WINAPI clearFileMappings();
extern "C" DWORD WINAPI hookWinAPIs( void * );
extern "C" DWORD WINAPI unhookWinAPIs( void * );


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
