//------------------------------------------------------------------------------
#ifndef headerScanner_HPP__343F36C2_0715_4B15_865A_D86ABF67EF5B
#define headerScanner_HPP__343F36C2_0715_4B15_865A_D86ABF67EF5B
//------------------------------------------------------------------------------
#include "utility_.hpp"

#include <clang/Frontend/CompilerInstance.h>
#include <llvm/ADT/Hashing.h>
#include <llvm/ADT/StringRef.h>
#include <llvm/ADT/OwningPtr.h>

#include <set>
#include <string>
#include <tuple>
#include <unordered_set>
#include <vector>

namespace clang
{
    class HeaderSearch;
}

namespace llvm
{
    class MemoryBuffer;
}

class Cache;
class HeaderTracker;

#define DEFINE_FLYWEIGHT(base, name) \
    struct name##Tag {}; \
    typedef Flyweight<base, name##Tag> name;

DEFINE_FLYWEIGHT(std::string, Dir);
DEFINE_FLYWEIGHT(std::string, HeaderName);
DEFINE_FLYWEIGHT(std::string, MacroName);
DEFINE_FLYWEIGHT(std::string, MacroValue);

struct HeaderLocation
{
    enum Enum
    {
        relative,
        regular,
        system
    };
};

struct Header
{
    Dir dir;
    HeaderName name;
    llvm::MemoryBuffer const * buffer;
    HeaderLocation::Enum loc;
};

struct HeaderHash
{
    std::size_t operator()( Header const & h )
    {
        return llvm::hash_combine
        (
            llvm::hash_value( h.dir.get() ),
            llvm::hash_value( h.name.get() )
        );
    }
};

inline bool operator==( Header const & l, Header const & r )
{
    return l.dir == r.dir &&
        l.name == r.name
    ;
}

typedef std::unordered_set<Header, HeaderHash> Headers;

typedef std::set<std::string> IgnoredHeaders;

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

    SearchPath     const & searchPath    () const { return searchPath_; }
    Defines        const & defines       () const { return defines_; }
    IgnoredHeaders const & ignoredHeaders() const { return ignoredHeaders_; }

private:
    SearchPath searchPath_;
    Defines defines_;
    IgnoredHeaders ignoredHeaders_;
};

class Preprocessor
{
public:
    explicit Preprocessor( Cache * cache );

    Headers scanHeaders( PreprocessingContext const &, std::string const & dir, std::string const & relFilename );
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
    std::unordered_map<clang::FileEntry const *, llvm::OwningPtr<llvm::MemoryBuffer> > contentCache_;
};


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
