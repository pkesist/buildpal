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
#include <llvm/ADT/OwningPtr.h>
#include <llvm/Support/Path.h>

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

#define DEFINE_FLYWEIGHT(base, name) \
    struct name##Tag {}; \
    typedef Flyweight<base, name##Tag> name;

DEFINE_FLYWEIGHT(llvm::SmallString<256>, Dir);
DEFINE_FLYWEIGHT(llvm::SmallString<64>, HeaderName);
DEFINE_FLYWEIGHT(llvm::SmallString<64>, MacroName);
DEFINE_FLYWEIGHT(llvm::SmallString<64 + 32>, MacroValue);

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

struct DummyModuleLoader : public clang::ModuleLoader 
{
    virtual clang::ModuleLoadResult loadModule(
        clang::SourceLocation,
        clang::ModuleIdPath,
        clang::Module::NameVisibilityKind,
        bool IsInclusionDirective) { return clang::ModuleLoadResult(); }
    virtual void makeModuleVisible(
        clang::Module *,
        clang::Module::NameVisibilityKind,
        clang::SourceLocation,
        bool Complain) {}
};

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

class Preprocessor
{
public:
    explicit Preprocessor( Cache * cache );

    bool scanHeaders( PreprocessingContext const & ppc, llvm::StringRef filename, Headers &, HeaderList & missingHeaders );
    void setMicrosoftMode( bool value ) { langOpts_->MicrosoftMode = value ? 1 : 0; }
    void setMicrosoftExt ( bool value ) { langOpts_->MicrosoftExt = value ? 1 : 0; }

private:
    std::size_t setupPreprocessor( PreprocessingContext const & ppc, llvm::StringRef filename );
    bool naivePreprocessing( llvm::StringRef fileName, Headers & );

private:
    clang::FileManager         & fileManager  ()       { return *fileManager_; }
    clang::FileManager   const & fileManager  () const { return *fileManager_; }
    clang::SourceManager       & sourceManager()       { return *sourceManager_; }
    clang::SourceManager const & sourceManager() const { return *sourceManager_; }
    clang::Preprocessor        & preprocessor ()       { return *preprocessor_; }
    clang::Preprocessor  const & preprocessor () const { return *preprocessor_; }

private:
    llvm::IntrusiveRefCntPtr<clang::DiagnosticIDs> diagID_;
    llvm::IntrusiveRefCntPtr<clang::DiagnosticOptions> diagOpts_;
    llvm::IntrusiveRefCntPtr<clang::DiagnosticsEngine> diagEng_;
    llvm::IntrusiveRefCntPtr<clang::PreprocessorOptions> ppOpts_;
    llvm::IntrusiveRefCntPtr<clang::LangOptions> langOpts_;
    llvm::IntrusiveRefCntPtr<clang::TargetOptions> targetOpts_;
    llvm::IntrusiveRefCntPtr<clang::TargetInfo> targetInfo_;
    llvm::IntrusiveRefCntPtr<clang::HeaderSearchOptions> hsOpts_;
    DummyModuleLoader moduleLoader_;
    clang::FileSystemOptions fsOpts_;
    llvm::OwningPtr<clang::FileManager> fileManager_;
    llvm::OwningPtr<clang::SourceManager> sourceManager_;
    llvm::OwningPtr<clang::HeaderSearch> headerSearch_;
    llvm::OwningPtr<clang::Preprocessor> preprocessor_;
    Cache * cache_;
};


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
