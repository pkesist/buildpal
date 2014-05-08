//------------------------------------------------------------------------------
#ifndef client_HPP__A5F2C5A2_924F_4D79_B482_A9C7E27A18B4
#define client_HPP__A5F2C5A2_924F_4D79_B482_A9C7E27A18B4
//------------------------------------------------------------------------------
#include <llvm/ADT/StringRef.h>
#include <llvm/ADT/Optional.h>

#include <string>
#include <vector>
#include <map>

typedef std::vector<std::string> PathList;

class Environment
{
    typedef std::map<std::string, std::string> EnvMap;
    EnvMap envMap_;

public:
    Environment() {}
    Environment( void * vpEnv, bool unicode );

    void remove( llvm::StringRef str );

    std::string createEnvBlock() const;

    llvm::Optional<std::string> get( llvm::StringRef str ) const;
};

PathList const & getPath( Environment const & );

bool findOnPath( PathList const & pathList, std::string const & file, std::string & result );

int createProcess( char const * appName, char * commandLine );
int createProcess( wchar_t const * appName, wchar_t * commandLine );

typedef int (*FallbackFunction)( void * );

int distributedCompile(
    llvm::StringRef compilerToolset,
    llvm::StringRef compilerExecutable,
    Environment const & env,
    wchar_t const * commandLine,
    llvm::StringRef portName,
    FallbackFunction fallbackFunc,
    void * fallbackParam
);


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
