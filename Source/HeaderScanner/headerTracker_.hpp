//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef headerTracker_HPP__A726F821_9CFA_4C46_838A_EDF69E6E6DF3
#define headerTracker_HPP__A726F821_9CFA_4C46_838A_EDF69E6E6DF3
//------------------------------------------------------------------------------
#include "headerScanner_.hpp"

#include "boost/optional.hpp"

#include <string>
#include <map>
#include <list>
#include <set>
#include <vector>
//------------------------------------------------------------------------------

namespace clang
{
    class Preprocessor;
    class SourceManager;
    class FileEntry;
    class MacroDirective;
    class HeaderSearch;
}


class HeaderTracker
{
public:
    typedef Preprocessor::HeaderRef Header;
    typedef Preprocessor::HeaderRefs Headers;
    typedef PreprocessingContext::IgnoredHeaders IgnoredHeaders;

    typedef boost::optional<std::string> MacroDef;

    explicit HeaderTracker( clang::SourceManager & sm )
        : sourceManager_( sm ), preprocessor_( 0 ), cacheHit_( 0 )
    {}

    void enterSourceFile( clang::FileEntry const * );
    Headers exitSourceFile();

    void findFile( llvm::StringRef fileName, bool const isAngled, clang::FileEntry const * & fileEntry );
    void headerSkipped( std::string const & relative );
    void enterHeader( std::string const & relative );
    void leaveHeader( IgnoredHeaders const & );

    void macroUsed( std::string const & name, clang::MacroDirective const * def );
    void macroDefined( std::string const & name, clang::MacroDirective const * def );
    void macroUndefined( std::string const & name, clang::MacroDirective const * def );

    void setPreprocessor( clang::Preprocessor * preprocessor )
    {
        preprocessor_ = preprocessor;
    }

    void setHeaderSearch( clang::HeaderSearch * headerSearch )
    {
        headerSearch_.reset( headerSearch );
    }

    bool inOverriddenFile() const
    {
        return cacheHit_ != 0;
    }

private:
    typedef std::pair<std::string, MacroDef> Macro;
    struct MacroUsage { enum Enum { macroUsed, macroDefined, macroUndefined }; };
    typedef std::pair<MacroUsage::Enum, Macro> MacroWithUsage;
    typedef std::list<MacroWithUsage> MacroUsages;
    typedef std::set<Macro> MacroSet;

    struct ShortCircuitEntry
    {
        ShortCircuitEntry( clang::FileEntry const * fileEntryp,
            MacroUsages const & macroUsagesp,
            Headers const & headersp )
            : fileEntry( fileEntryp ),
            macroUsages( macroUsagesp ),
            headers( headersp )
        {}

        clang::FileEntry const * fileEntry;
        MacroUsages macroUsages;
        Headers headers;
    };

    struct HeaderShortCircuit : public std::map<MacroSet, ShortCircuitEntry> {};
    struct HeaderCacheSt : public std::map<clang::FileEntry const *, HeaderShortCircuit> {};

    struct HeaderCtx
    {
    public:
        explicit HeaderCtx( Header const & header )
            : header_( header ) {}

        void addMacro( MacroUsage::Enum const usage, Macro const & macro )
        {
            macroUsages_.push_back( std::make_pair( usage, macro ) );
        }

        void addHeader( Header const & header )
        {
            includedHeaders_.insert( header );
        }

        void addStuff( MacroUsages const * macroUsages, Headers const * headers )
        {
            if ( macroUsages )
            {
                std::copy( macroUsages->begin(), macroUsages->end(),
                    std::back_inserter( macroUsages_ ) );
            }

            if ( headers )
            {
                std::copy( headers->begin(), headers->end(),
                    std::inserter( includedHeaders_, includedHeaders_.begin() ) );
            }
        }

        MacroUsages const & macroUsages() const { return macroUsages_; }
        Headers const & includedHeaders() const { return includedHeaders_; }
        Header const & header() { return header_; }

        HeaderShortCircuit::value_type makeCacheEntry( clang::SourceManager & ) const;

    private:
        Header header_;
        MacroUsages macroUsages_;
        Headers includedHeaders_;
    };
    typedef std::vector<HeaderCtx> HeaderCtxStack;

    HeaderCtxStack const & headerCtxStack() const { return headerCtxStack_; }
    HeaderCtxStack       & headerCtxStack()       { return headerCtxStack_; }

    HeaderCacheSt const & cache() const { return cache_; }
    HeaderCacheSt       & cache()       { return cache_; }

    clang::Preprocessor & preprocessor() const { assert( preprocessor_ ); return *preprocessor_; }
    clang::SourceManager & sourceManager() const { return sourceManager_; }

    MacroDef macroDefFromSourceLocation( clang::MacroDirective const * def );

private:
    llvm::OwningPtr<clang::HeaderSearch> headerSearch_;
    clang::SourceManager & sourceManager_;
    clang::Preprocessor * preprocessor_;
    HeaderCtxStack headerCtxStack_;
    HeaderShortCircuit::value_type * cacheHit_;
    HeaderCacheSt cache_;
    std::vector<clang::FileEntry const *> fileStack_;
};


//------------------------------------------------------------------------------
#endif