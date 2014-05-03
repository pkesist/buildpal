#include <llvm/ADT/StringRef.h>

#include <string>
#include <vector>

typedef std::vector<std::string> PathList;

PathList const & getPath();

bool findOnPath( PathList const & pathList, std::string const & file, std::string & result );

int createProcess( char * commandLine );
int createProcess( wchar_t * commandLine );

typedef int (*FallbackFunction)();

wchar_t const * findArgs( wchar_t const * cmdLine );

int distributedCompile(
    llvm::StringRef compilerToolset,
    llvm::StringRef compilerExecutable,
    wchar_t * commandLine,
    llvm::StringRef portName,
    FallbackFunction fallbackFunc
);
