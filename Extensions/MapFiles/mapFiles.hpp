//------------------------------------------------------------------------------
#ifndef mapFiles_HPP__A6FF475B_B11B_486F_B491_549FBAFAEA1A
#define mapFiles_HPP__A6FF475B_B11B_486F_B491_549FBAFAEA1A
//------------------------------------------------------------------------------
#include <Windows.h>
//------------------------------------------------------------------------------

DWORD WINAPI hookWinAPIs();
DWORD WINAPI unhookWinAPIs();

BOOL mapFileGlobalA( char const * virtualFile, char const * file );
BOOL mapFileGlobalW( wchar_t const * virtualFile, wchar_t const * file );
BOOL unmapFileGlobalA( char const * virtualFile );
BOOL unmapFileGlobalW( wchar_t const * virtualFile );

DWORD createFileMap();
void destroyFileMap( DWORD );
BOOL mapFileA( DWORD fileMap, char const * virtualFile, char const * file );
BOOL mapFileW( DWORD fileMap, wchar_t * virtualFile, wchar_t * file );
BOOL WINAPI createProcessWithMappingA(
  _In_opt_     char const * lpApplicationName,
  _Inout_opt_  char * lpCommandLine,
  _In_opt_     LPSECURITY_ATTRIBUTES lpProcessAttributes,
  _In_opt_     LPSECURITY_ATTRIBUTES lpThreadAttributes,
  _In_         BOOL bInheritHandles,
  _In_         DWORD dwCreationFlags,
  _In_opt_     LPVOID lpEnvironment,
  _In_opt_     char const * lpCurrentDirectory,
  _In_         LPSTARTUPINFOA lpStartupInfo,
  _Out_        LPPROCESS_INFORMATION lpProcessInformation,
  _In_         DWORD const * fileMaps,
  _In_         DWORD fileMapsCount
);

BOOL WINAPI createProcessWithMappingW(
  _In_opt_     wchar_t const * lpApplicationName,
  _Inout_opt_  wchar_t * lpCommandLine,
  _In_opt_     LPSECURITY_ATTRIBUTES lpProcessAttributes,
  _In_opt_     LPSECURITY_ATTRIBUTES lpThreadAttributes,
  _In_         BOOL bInheritHandles,
  _In_         DWORD dwCreationFlags,
  _In_opt_     LPVOID lpEnvironment,
  _In_opt_     wchar_t const * lpCurrentDirectory,
  _In_         LPSTARTUPINFOW lpStartupInfo,
  _Out_        LPPROCESS_INFORMATION lpProcessInformation,
  _In_         DWORD const * fileMaps,
  _In_         DWORD fileMapsCount
);

DWORD WINAPI Initialize( HANDLE readHandle, BOOL suspend );

//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
