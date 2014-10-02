//------------------------------------------------------------------------------
#ifndef headerScanner_HPP__343F36C2_0715_4B15_865A_D86ABF67EF5B
#define headerScanner_HPP__343F36C2_0715_4B15_865A_D86ABF67EF5B
//------------------------------------------------------------------------------
#include "utility_.hpp"

#include "contentEntry_.hpp"

#include <clang/Basic/TargetInfo.h>
#include <clang/Basic/DiagnosticOptions.h>
#include <clang/Basic/DiagnosticIDs.h>
#include <clang/Basic/FileManager.h>
#include <clang/Basic/SourceManager.h>
#include <clang/Lex/ModuleLoader.h>
#include <clang/Lex/Preprocessor.h>
#include <clang/Lex/PreprocessorOptions.h>
#include <clang/Lex/HeaderSearch.h>
#include <clang/Lex/HeaderSearchOptions.h>
#include <llvm/ADT/Hashing.h>
#include <llvm/ADT/IntrusiveRefCntPtr.h>
#include <llvm/ADT/StringRef.h>
#include <llvm/Support/Path.h>

#include <memory>
#include <set>
#include <string>
#include <tuple>
#include <unordered_set>
#include <vector>

//#define DEBUG_HEADERS 1

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


DEFINE_FLYWEIGHT(llvm::SmallString<256>, Dir);
DEFINE_FLYWEIGHT(llvm::SmallString<64>, HeaderName);

struct Header
{
    Dir dir;
    HeaderName name;
    ContentEntryPtr contentEntry;
    bool relative;
};

inline bool operator==( Header const & first, Header const & second )
{
    return ( first.dir == second.dir ) && ( first.name == second.name );
}

inline bool operator<( Header const & first, Header const & second )
{
    return ( first.dir < second.dir ) || ( ( first.dir == second.dir ) && ( first.name < second.name ) );
}


void normalize( llvm::SmallString<512> & path );

typedef std::set<Header> Headers;

typedef std::set<std::string> HeaderList;

class PreprocessingContext
{
public:
    void addIncludePath( llvm::StringRef path, bool sysinclude )
    {
        if ( path.empty() )
            return;
        if ( sysinclude )
        {
            llvm::SmallString<512> tmp( path );
            normalize( tmp );
            systemSearchPath_.push_back( tmp );
        }
        else
        {
            llvm::SmallString<512> tmp( path );
            normalize( tmp );
            userSearchPath_.push_back( tmp );
        }
    }

    void addMacro( llvm::StringRef name, llvm::StringRef value )
    {
        defines_.push_back( std::make_pair( name, value ) );
    }

    void addForcedInclude( llvm::StringRef include )
    {
        forcedIncludes_.push_back( include );
    }

    typedef std::vector<llvm::SmallString<512> > SearchPath;
    typedef std::vector<std::pair<std::string, std::string> > Defines;
    typedef std::vector<std::string> Includes;

    SearchPath const & userSearchPath  () const { return userSearchPath_; }
    SearchPath const & systemSearchPath() const { return systemSearchPath_; }
    Defines    const & defines         () const { return defines_; }
    Includes   const & forcedIncludes  () const { return forcedIncludes_; }

private:
    SearchPath userSearchPath_;
    SearchPath systemSearchPath_;
    Defines defines_;
    Includes forcedIncludes_;
};

struct Statistics
{
    Statistics() : filesPreprocessedRegularly( 0 ), filesPreprocessedNaively( 0 ) {}

    std::atomic<std::size_t> filesPreprocessedRegularly;
    std::atomic<std::size_t> filesPreprocessedNaively;
};

class Preprocessor
{
public:
    explicit Preprocessor( Cache * cache );

    bool scanHeaders( PreprocessingContext const & ppc, llvm::StringRef filename, Headers &, HeaderList & missingHeaders );
    void setMicrosoftMode( bool value ) { langOpts_->MSVCCompat = value ? 1 : 0; }
    void setMicrosoftExt ( bool value ) { langOpts_->MicrosoftExt = value ? 1 : 0; }

    Statistics const & statistics() const { return statistics_; }
    Statistics       & statistics()       { return statistics_; }

private:
    clang::LangOptions & langOpts() { return *langOpts_; }

private:
    llvm::IntrusiveRefCntPtr<clang::DiagnosticIDs> diagID_;
    llvm::IntrusiveRefCntPtr<clang::DiagnosticOptions> diagOpts_;
    llvm::IntrusiveRefCntPtr<clang::PreprocessorOptions> ppOpts_;
    llvm::IntrusiveRefCntPtr<clang::LangOptions> langOpts_;
    std::shared_ptr<clang::TargetOptions> targetOpts_;
    llvm::IntrusiveRefCntPtr<clang::HeaderSearchOptions> hsOpts_;
    Statistics statistics_;
    clang::FileSystemOptions fsOpts_;
    Cache * cache_;
};


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
