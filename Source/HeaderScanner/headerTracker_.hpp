//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef headerTracker_HPP__A726F821_9CFA_4C46_838A_EDF69E6E6DF3
#define headerTracker_HPP__A726F821_9CFA_4C46_838A_EDF69E6E6DF3
//------------------------------------------------------------------------------
#include "headerScanner_.hpp"

#include "headerCache_.hpp"
#include "utility_.hpp"

#include "boost/bind.hpp"

#include <string>
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
    typedef PreprocessingContext::IgnoredHeaders IgnoredHeaders;

    explicit HeaderTracker( clang::Preprocessor & preprocessor, std::pair<clang::HeaderSearch *, clang::HeaderSearch *> headerSearch, Cache * cache )
        : userHeaderSearch_( headerSearch.first ), systemHeaderSearch_( headerSearch.second ), preprocessor_( preprocessor ), cache_( cache )
    {
    }

    void enterSourceFile( clang::FileEntry const * );
    Preprocessor::HeaderRefs exitSourceFile();

    void findFile( llvm::StringRef fileName, bool const isAngled, clang::FileEntry const * & fileEntry );
    void headerSkipped( llvm::StringRef relative );
    void enterHeader( llvm::StringRef relative );
    void leaveHeader( IgnoredHeaders const & );

    void macroUsed( llvm::StringRef name, clang::MacroDirective const * def );
    void macroDefined( llvm::StringRef name, clang::MacroDirective const * def );
    void macroUndefined( llvm::StringRef name, clang::MacroDirective const * def );

private:
    struct HeaderCtx
    {
    public:
        explicit HeaderCtx( HeaderName const & header, CacheEntryPtr const & cacheHit, clang::Preprocessor const & preprocessor )
            :
            header_( header ),
            cacheHit_( cacheHit ),
            preprocessor_( preprocessor )
        {
            if ( cacheHit_ )
                includedHeaders_.push_back( cacheHit );
        }

        void macroUsed( llvm::StringRef macroName, llvm::StringRef macroDef )
        {
            assert ( !fromCache() );
            MacroRef const macro( std::make_pair( macroName, macroDef ) );
            if ( definedMacros_.find( macro.first ) == definedMacros_.end() )
                usedMacros_.insert( macro );
        }

        void macroDefined( llvm::StringRef macroName, llvm::StringRef macroDef )
        {
            assert ( !fromCache() );
            MacroRef const macro( std::make_pair( macroName, macroDef ) );
            headerContent_.push_back( std::make_pair( MacroUsage::defined, macro ) );
            definedMacros_.insert( macroName );
        }

        void macroUndefined( llvm::StringRef macroName )
        {
            assert ( !fromCache() );
            MacroRef const macro( std::make_pair( macroName, llvm::StringRef() ) );
            headerContent_.push_back( std::make_pair( MacroUsage::undefined, macro ) );
        }

        void addHeader( HeaderName const & header )
        {
            assert ( !fromCache() );
            includedHeaders_.push_back( header );
        }

        void addStuff( CacheEntryPtr const & cacheEntry, bool ignoreHeaders )
        {
            Macros::const_iterator       cacheIter = cacheEntry->usedMacros().begin();
            Macros::const_iterator const cacheEnd = cacheEntry->usedMacros().end();
            DefinedMacros::const_iterator       definedIter = definedMacros_.begin();
            DefinedMacros::const_iterator const definedEnd = definedMacros_.end();
            while ( cacheIter != cacheEnd && definedIter != definedEnd )
            {
                if ( cacheIter->first < *definedIter )
                {
                    usedMacros_.insert( MacroRefs::value_type( cacheIter->first, cacheIter->second ) );
                    ++cacheIter;
                }
                else if ( cacheIter->first > *definedIter )
                {
                    ++definedIter;
                }
                else
                {
                    ++cacheIter;
                    ++definedIter;
                }
            }
            std::copy( cacheIter, cacheEnd, std::inserter( usedMacros_, usedMacros_.begin() ) );

            headerContent_.push_back( cacheEntry );
            if ( !ignoreHeaders )
                includedHeaders_.push_back( cacheEntry );
        }

        void addHeaders( Headers const & headers )
        {
            std::copy( headers.begin(), headers.end(),
                std::inserter( includedHeaders_, includedHeaders_.begin() ) );
        }

        MacroRefs const & usedMacros() const { assert( !fromCache() ); return usedMacros_; }
        HeaderContent const & headerContent() const { return cacheHit_ ? cacheHit_->headerContent() : headerContent_; }
        Headers const & includedHeaders() const { return includedHeaders_; }
        HeaderName const & header() { return header_; }

        CacheEntryPtr addToCache( Cache &, clang::FileEntry const * file, clang::SourceManager & ) const;

        CacheEntryPtr const & cacheHit() const { return cacheHit_; }

        bool fromCache() const { return cacheHit_; }

    private:
        typedef std::set<llvm::StringRef> DefinedMacros;

    private:
        clang::Preprocessor const & preprocessor_;
        HeaderName header_;
        CacheEntryPtr cacheHit_;
        MacroRefs usedMacros_;
        DefinedMacros definedMacros_;
        HeaderContent headerContent_;
        Headers includedHeaders_;
    };
    typedef std::vector<HeaderCtx> HeaderCtxStack;

    HeaderCtxStack const & headerCtxStack() const { return headerCtxStack_; }
    HeaderCtxStack       & headerCtxStack()       { return headerCtxStack_; }

    bool cacheDisabled() const { return cache_ == 0; }
    Cache      const & cache() const { return *cache_; }
    Cache            & cache()       { return *cache_; }
    MacroState const & macroState() const { return macroState_; }
    MacroState       & macroState()       { return macroState_; }

    clang::Preprocessor & preprocessor() const { return preprocessor_; }
    clang::SourceManager & sourceManager() const;

private:
    llvm::OwningPtr<clang::HeaderSearch> userHeaderSearch_;
    llvm::OwningPtr<clang::HeaderSearch> systemHeaderSearch_;
    clang::Preprocessor & preprocessor_;
    HeaderCtxStack headerCtxStack_;
    Cache * cache_;
    CacheEntryPtr cacheHit_;
    std::vector<std::pair<clang::FileEntry const *, bool> > fileStack_;
    MacroState macroState_;
};


//------------------------------------------------------------------------------
#endif