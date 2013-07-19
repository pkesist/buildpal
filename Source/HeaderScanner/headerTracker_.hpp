//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef headerTracker_HPP__A726F821_9CFA_4C46_838A_EDF69E6E6DF3
#define headerTracker_HPP__A726F821_9CFA_4C46_838A_EDF69E6E6DF3
//------------------------------------------------------------------------------
#include "headerScanner_.hpp"

#include "headerCache_.hpp"

#include "boost/bind.hpp"

#include <string>
#include <map>
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

    explicit HeaderTracker( clang::SourceManager & sm, Cache & cache )
        : sourceManager_( sm ), cache_( cache ), preprocessor_( 0 ), cacheHit_( 0 )
    {}

    void enterSourceFile( clang::FileEntry const * );
    Headers exitSourceFile();

    void findFile( llvm::StringRef fileName, bool const isAngled, clang::FileEntry const * & fileEntry );
    void headerSkipped( llvm::StringRef relative );
    void enterHeader( llvm::StringRef relative );
    void leaveHeader( IgnoredHeaders const & );

    void macroUsed( llvm::StringRef name, clang::MacroDirective const * def );
    void macroDefined( llvm::StringRef name, clang::MacroDirective const * def );
    void macroUndefined( llvm::StringRef name, clang::MacroDirective const * def );

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
    struct HeaderCtx
    {
    public:
        explicit HeaderCtx( Header const & header )
            : header_( header ) {}

        void macroUsed( Macro const & macro )
        {
            macroUsages_.push_back( std::make_pair( MacroUsage::used, macro ) );
            if ( definedMacros_.find( macro.first ) == definedMacros_.end() )
                usedMacros_.insert( macro );
        }

        void macroDefined( Macro const & macro )
        {
            macroUsages_.push_back( std::make_pair( MacroUsage::defined, macro ) );
            definedMacros_.insert( macro.first );
        }

        void macroUndefined( Macro const & macro )
        {
            macroUsages_.push_back( std::make_pair( MacroUsage::undefined, macro ) );
        }

        void addHeader( Header const & header )
        {
            includedHeaders_.insert( header );
        }

        void addMacroUsage( MacroWithUsage const & macroWithUsage )
        {
            switch ( macroWithUsage.first )
            {
                case MacroUsage::used: macroUsed( macroWithUsage.second ); break;
                case MacroUsage::defined: macroDefined( macroWithUsage.second ); break;
                case MacroUsage::undefined: macroUndefined( macroWithUsage.second ); break;
                default: assert( !"Invalid macro usage." );
            }
        }

        template <typename Headers>
        void addStuff( MacroUsages const & macroUsages, Headers const * headers )
        {
            std::for_each( macroUsages.begin(), macroUsages.end(),
                    boost::bind( &HeaderTracker::HeaderCtx::addMacroUsage, this, _1 ) );

            if ( headers )
            {
                std::copy( headers->begin(), headers->end(),
                    std::inserter( includedHeaders_, includedHeaders_.begin() ) );
            }
        }

        Macros const & usedMacros() const { return usedMacros_; }
        MacroUsages const & macroUsages() const { return macroUsages_; }
        Headers const & includedHeaders() const { return includedHeaders_; }
        Header const & header() { return header_; }

        void addToCache( Cache &, clang::FileEntry const * file, clang::SourceManager & ) const;

    private:
        Header header_;
        
        typedef std::map<llvm::StringRef, llvm::StringRef> MacroMap;

        Macros usedMacros_;
        std::set<llvm::StringRef> definedMacros_;
        MacroUsages macroUsages_;
        Headers includedHeaders_;
    };
    typedef std::vector<HeaderCtx> HeaderCtxStack;

    HeaderCtxStack const & headerCtxStack() const { return headerCtxStack_; }
    HeaderCtxStack       & headerCtxStack()       { return headerCtxStack_; }

    Cache const & cache() const { return cache_; }
    Cache       & cache()       { return cache_; }

    clang::Preprocessor & preprocessor() const { assert( preprocessor_ ); return *preprocessor_; }
    clang::SourceManager & sourceManager() const { return sourceManager_; }

    llvm::StringRef macroDefFromSourceLocation( clang::MacroDirective const * def );

private:
    llvm::OwningPtr<clang::HeaderSearch> headerSearch_;
    clang::SourceManager & sourceManager_;
    clang::Preprocessor * preprocessor_;
    HeaderCtxStack headerCtxStack_;
    Cache & cache_;
    Cache::CacheHit * cacheHit_;
    std::set<Cache::CacheHit *> cacheEntriesUsed_;
    std::vector<clang::FileEntry const *> fileStack_;
};


//------------------------------------------------------------------------------
#endif