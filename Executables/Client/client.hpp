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
    mutable std::string envBlock_;

public:
    Environment() {}
    Environment( void * vpEnv, bool unicode );

    void remove( llvm::StringRef key );
    void add( llvm::StringRef key, llvm::StringRef val );

    char * createEnvBlock() const;

    llvm::Optional<std::string> get( llvm::StringRef str ) const;
};

PathList const & getPath( Environment const & );

bool findOnPath( PathList const & pathList, std::string const & file, std::string & result );

int createProcess(
    char const * appName,
    char * commandLine,
    Environment const * env = 0,
    char const * curDir = 0
);

int createProcess(
    wchar_t const * appName,
    wchar_t * commandLine,
    Environment const * env = 0,
    wchar_t const * curDir = 0
);

typedef int (*FallbackFunction)( void * );

int distributedCompile(
    char const * compilerToolset,
    char const * compilerExecutable,
    Environment const & env,
    char const * commandLine,
    char const * cwd,
    char const * portName,
    FallbackFunction fallbackFunc,
    void * fallbackParam
);


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
