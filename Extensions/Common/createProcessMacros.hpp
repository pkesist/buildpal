//------------------------------------------------------------------------------
#ifndef createProcessMacros_HPP__9E38915A_F7A8_4F80_8082_D0C9A84F0594
#define createProcessMacros_HPP__9E38915A_F7A8_4F80_8082_D0C9A84F0594
//------------------------------------------------------------------------------

#define CREATE_PROCESS_PARAMSW \
  LPCWSTR lpApplicationName, \
  LPWSTR lpCommandLine, \
  LPSECURITY_ATTRIBUTES lpProcessAttributes, \
  LPSECURITY_ATTRIBUTES lpThreadAttributes, \
  BOOL bInheritHandles, \
  DWORD dwCreationFlags, \
  LPVOID lpEnvironment, \
  LPCWSTR lpCurrentDirectory, \
  LPSTARTUPINFOW lpStartupInfo, \
  LPPROCESS_INFORMATION lpProcessInformation

#define CREATE_PROCESS_PARAMSA \
  LPCSTR lpApplicationName, \
  LPSTR lpCommandLine, \
  LPSECURITY_ATTRIBUTES lpProcessAttributes, \
  LPSECURITY_ATTRIBUTES lpThreadAttributes, \
  BOOL bInheritHandles, \
  DWORD dwCreationFlags, \
  LPVOID lpEnvironment, \
  LPCSTR lpCurrentDirectory, \
  LPSTARTUPINFOA lpStartupInfo, \
  LPPROCESS_INFORMATION lpProcessInformation

#define CREATE_PROCESS_ARGS \
  lpApplicationName, \
  lpCommandLine, \
  lpProcessAttributes, \
  lpThreadAttributes, \
  bInheritHandles, \
  dwCreationFlags, \
  lpEnvironment, \
  lpCurrentDirectory, \
  lpStartupInfo, \
  lpProcessInformation


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
