#include <llvm/ADT/StringRef.h>
#include <string>
#include <vector>

typedef std::vector<std::string> PathList;

PathList const & getPath();

bool findOnPath( PathList const & pathList, std::string const & file, std::string & result );

int createProcess( char * commandLine );

typedef int (*FallbackFunction)();

int distributedCompile(
    llvm::StringRef compilerToolset,
    llvm::StringRef compilerExecutable,
    int argc,
    char const * const argv[],
    llvm::StringRef portName,
    FallbackFunction fallbackFunc
);
