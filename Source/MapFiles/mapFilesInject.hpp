//------------------------------------------------------------------------------
#ifndef mapFilesInject_HPP__A6FF475B_B11B_486F_B491_549FBAFAEA1A
#define mapFilesInject_HPP__A6FF475B_B11B_486F_B491_549FBAFAEA1A
//------------------------------------------------------------------------------
#include <unordered_map>
#include <string>

#include <Windows.h>
//------------------------------------------------------------------------------

extern "C" BOOL WINAPI addFileMapping( char const * virtualEntry, char const * realEntry );
extern "C" BOOL WINAPI removeFileMapping( char const * virtualEntry );
extern "C" BOOL WINAPI clearFileMappings();
extern "C" DWORD WINAPI hookWinAPIs( void * );
extern "C" DWORD WINAPI unhookWinAPIs( void * );

typedef std::unordered_map<std::string, std::string> FileMapping;

extern "C" BOOL WINAPI createProcessWithOverridesA(
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
               FileMapping const & fileMapping
);

extern "C" BOOL WINAPI createProcessWithOverridesW(
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
               FileMapping const & fileMapping
);



//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
