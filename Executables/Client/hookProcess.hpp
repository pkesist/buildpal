//------------------------------------------------------------------------------
#ifndef hookProcess_HPP__650DBA06_5BC9_41C5_9242_C39C79C17AFD
#define hookProcess_HPP__650DBA06_5BC9_41C5_9242_C39C79C17AFD
//------------------------------------------------------------------------------
#include "../../Extensions/Common/createProcessMacros.hpp"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

BOOL WINAPI createProcessA( CREATE_PROCESS_PARAMSA );
BOOL WINAPI createProcessW( CREATE_PROCESS_PARAMSW );

void registerCompiler( char const * compilerPath, char const * replacement );
void setPortName( char const * portName );


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
