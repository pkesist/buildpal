//------------------------------------------------------------------------------
#ifndef mapFilesInject_HPP__A6FF475B_B11B_486F_B491_549FBAFAEA1A
#define mapFilesInject_HPP__A6FF475B_B11B_486F_B491_549FBAFAEA1A
//------------------------------------------------------------------------------
#include <Windows.h>
//------------------------------------------------------------------------------

extern "C" DWORD WINAPI hookWinAPIs();
extern "C" DWORD WINAPI unhookWinAPIs();

extern "C" BOOL mapFileGlobalA( char const * virtualFile, char const * file );
extern "C" BOOL mapFileGlobalW( wchar_t const * virtualFile, wchar_t const * file );
extern "C" BOOL unmapFileGlobalA( char const * virtualFile );
extern "C" BOOL unmapFileGlobalW( wchar_t const * virtualFile );

extern "C" DWORD createFileMap();
extern "C" BOOL mapFileA( DWORD, char const * virtualFile, char const * file );
extern "C" BOOL mapFileW( DWORD, wchar_t * virtualFile, wchar_t * file );
extern "C" BOOL WINAPI createProcessWithMappingA(
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
  _In_         DWORD fileMap
);

extern "C" BOOL WINAPI createProcessWithMappingW(
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
  _In_         DWORD fileMap
);

extern "C" DWORD WINAPI Initialize( HANDLE readHandle );

//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
