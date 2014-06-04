//------------------------------------------------------------------------------
#ifndef createProcess_HPP__D0A2E26E_D6BE_4EDA_B64C_42C1E59FA8E9
#define createProcess_HPP__D0A2E26E_D6BE_4EDA_B64C_42C1E59FA8E9
//------------------------------------------------------------------------------
#include <Python.h>

#include <windows.h>
//------------------------------------------------------------------------------

typedef BOOL (WINAPI *CreateProcessFunc)(
  LPCWSTR /*lpApplicationName*/,
  LPWSTR /*lpCommandLine*/,
  LPSECURITY_ATTRIBUTES /*lpProcessAttributes*/,
  LPSECURITY_ATTRIBUTES /*lpThreadAttributes*/,
  BOOL /*bInheritHandles*/,
  DWORD /*dwCreationFlags*/,
  LPVOID /*lpEnvironment*/,
  LPCWSTR /*lpCurrentDirectory*/,
  LPSTARTUPINFOW /*lpStartupInfo*/,
  LPPROCESS_INFORMATION /*lpProcessInformation*/,
  void * extraData);

PyObject * pythonCreateProcess( PyObject * args, CreateProcessFunc cpFunc, void * cpData );

//------------------------------------------------------------------------------
#endif
