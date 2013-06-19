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
    void addIncludePath( std::string const & path, bool sysinclude )
    {
        if ( path.empty() )
            return;
        searchPath_.push_back( std::make_pair( path, sysinclude ) );
    }

    void addMacro( std::string const & name, std::string const & value )
    {
        defines_.push_back( std::make_pair( name, value ) );
    }

    typedef std::vector<std::pair<std::string, bool> > SearchPath;
    typedef std::vector<std::pair<std::string, std::string> > Defines;

    SearchPath const & searchPath() const { return searchPath_; }
    Defines    const & defines   () const { return defines_; }

private:
    SearchPath searchPath_;
    Defines defines_;
};

class Preprocessor
{
public:
    Preprocessor();

    typedef std::set<std::string> HeaderList;
    typedef std::pair<std::string, std::string> HeaderRef;
    typedef std::set<HeaderRef> HeaderRefs;
    HeaderRefs scanHeaders( PreprocessingContext const &, std::string const & filename, HeaderList const & headersToSkip, std::string const & pth );
    std::string & preprocess( PreprocessingContext const &, std::string const & filename, std::string & output );

    void setMicrosoftMode( bool value ) { compiler().getLangOpts().MicrosoftMode = value ? 1 : 0; }
    void setMicrosoftExt ( bool value ) { compiler().getLangOpts().MicrosoftExt = value ? 1 : 0; }

    void emitPTH( PreprocessingContext const & ppc, std::string const & src, std::string const & output );

private:
    void setupPreprocessor( PreprocessingContext const & ppc, std::string const & filename );

private:
    clang::CompilerInstance       & compiler()       { return compiler_; }
    clang::CompilerInstance const & compiler() const { return compiler_; }
    clang::Preprocessor       & preprocessor()       { return compiler_.getPreprocessor(); }
    clang::Preprocessor const & preprocessor() const { return compiler_.getPreprocessor(); }

private:
    clang::CompilerInstance compiler_;
};


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
