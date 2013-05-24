//------------------------------------------------------------------------------
#ifndef headerScanner_HPP__343F36C2_0715_4B15_865A_D86ABF67EF5B
#define headerScanner_HPP__343F36C2_0715_4B15_865A_D86ABF67EF5B
//------------------------------------------------------------------------------
#include "clang/Frontend/CompilerInstance.h"

#include <set>
#include <string>
#include <vector>

class PreprocessingContext
{
public:
    PreprocessingContext( std::string const & filename );
    void addIncludePath( std::string const & path, bool sysinclude );
    void addMacro( std::string const & name, std::string const & value );

    typedef std::pair<std::string, std::string> HeaderRef;
    typedef std::set<HeaderRef> HeaderRefs;
    HeaderRefs scanHeaders();
    
private:
    void addIncludePathWorker( std::string const & path, bool sysinclude );

private:
    clang::CompilerInstance compiler_;
    std::vector<std::pair<std::string, bool> > searchPath_;
    std::vector<std::pair<std::string, std::string> > defines_;
};


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
