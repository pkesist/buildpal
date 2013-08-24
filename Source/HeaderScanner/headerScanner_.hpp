//------------------------------------------------------------------------------
#ifndef headerScanner_HPP__343F36C2_0715_4B15_865A_D86ABF67EF5B
#define headerScanner_HPP__343F36C2_0715_4B15_865A_D86ABF67EF5B
//------------------------------------------------------------------------------
#include "clang/Frontend/CompilerInstance.h"
#include "llvm/ADT/OwningPtr.h"

#include <map>
#include <set>
#include <string>
#include <vector>

namespace clang
{
    class HeaderSearch;
}

class Cache;
class HeaderTracker;

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

    void addIgnoredHeader( std::string const & name )
    {
        ignoredHeaders_.insert( name );
    }

    typedef std::vector<std::pair<std::string, bool> > SearchPath;
    typedef std::vector<std::pair<std::string, std::string> > Defines;
    typedef std::set<std::string> IgnoredHeaders;

    SearchPath     const & searchPath    () const { return searchPath_; }
    Defines        const & defines       () const { return defines_; }
    IgnoredHeaders const & ignoredHeaders() const { return ignoredHeaders_; }

private:
    SearchPath searchPath_;
    Defines defines_;
    IgnoredHeaders ignoredHeaders_;
};

struct HeaderRef
{
    HeaderRef( std::string const & rel, char const * d, std::size_t s )
        : relative( rel ), data( d ), size( s )
    {}

    std::string relative;
    char const * data;
    std::size_t size;

    bool operator<( HeaderRef const & other ) const
    {
        if ( relative < other.relative )
            return true;
        return false;
    }

    bool operator==( HeaderRef const & other ) const
    {
        return relative == other.relative;
    }
};

class Preprocessor
{
public:
    explicit Preprocessor( Cache * );

    typedef HeaderRef HeaderRef;
    typedef std::set<HeaderRef> HeaderRefs;
    HeaderRefs scanHeaders( PreprocessingContext const &, std::string const & filename );
    std::string & rewriteIncludes( PreprocessingContext const &, std::string const & filename, std::string & output );
    std::string & preprocess( PreprocessingContext const &, std::string const & filename, std::string & output );
    clang::HeaderSearch * getHeaderSearch( PreprocessingContext::SearchPath const & searchPath );

    void setMicrosoftMode( bool value ) { compiler().getLangOpts().MicrosoftMode = value ? 1 : 0; }
    void setMicrosoftExt ( bool value ) { compiler().getLangOpts().MicrosoftExt = value ? 1 : 0; }

private:
    void setupPreprocessor( PreprocessingContext const & ppc, std::string const & filename );

private:
    clang::CompilerInstance       & compiler     ()       { return compiler_; }
    clang::CompilerInstance const & compiler     () const { return compiler_; }
    clang::SourceManager          & sourceManager()       { return compiler_.getSourceManager(); }
    clang::SourceManager    const & sourceManager() const { return compiler_.getSourceManager(); }
    clang::Preprocessor           & preprocessor ()       { return compiler_.getPreprocessor(); }
    clang::Preprocessor     const & preprocessor () const { return compiler_.getPreprocessor(); }

private:
    clang::CompilerInstance compiler_;
    Cache * cache_;
};


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
