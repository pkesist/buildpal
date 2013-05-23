//------------------------------------------------------------------------------
#ifndef headerScanner_HPP__343F36C2_0715_4B15_865A_D86ABF67EF5B
#define headerScanner_HPP__343F36C2_0715_4B15_865A_D86ABF67EF5B
//------------------------------------------------------------------------------
#include "clang/Frontend/CompilerInstance.h"

#include <set>
#include <string>

class PreprocessingContext
{
public:
    PreprocessingContext( std::string const & filename );
    void addIncludePath( std::string const & path, bool sysinclude );

    std::set<std::string> scanHeaders();
    
private:
    clang::CompilerInstance m_compiler;
};


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
