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
    typedef PreprocessingContext::IgnoredHeaders IgnoredHeaders;

    explicit HeaderTracker( clang::Preprocessor & preprocessor, clang::HeaderSearch & headerSearch, Cache * cache )
        : headerSearch_( &headerSearch ), preprocessor_( preprocessor ), cache_( cache )
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

    void setHeaderSearch( clang::HeaderSearch * headerSearch )
    {
        headerSearch_.reset( headerSearch );
    }

    bool inOverriddenFile() const
    {
        return cacheHit_.get() != 0;
    }

private:
    struct HeaderCtx
    {
    public:
        explicit HeaderCtx( HeaderName const & header, std::shared_ptr<Cache::CacheEntry> const & cacheHit )
            :
            header_( header ),
            cacheHit_( cacheHit )
        {
            if ( cacheHit_ )
                includedHeaders_.push_back( cacheHit );
        }

        void macroUsed( Macro const & macro )
        {
            if ( cacheHit_ )
                return;
            if ( usedMacros_.find( macro ) != usedMacros_.end() )
                // We already know about this.
                return;
            if ( definedMacros_.find( macro ) == definedMacros_.end() )
                usedMacros_.insert( macro );
        }

        void macroDefined( Macro const & macro )
        {
            if ( cacheHit_ )
                return;
            headerContent_.push_back( std::make_pair( MacroUsage::defined, macro ) );
            definedMacros_.insert( macro );
        }

        void macroUndefined( Macro const & macro )
        {
            if ( cacheHit_ )
                return;
            headerContent_.push_back( std::make_pair( MacroUsage::undefined, macro ) );
        }

        void addHeader( HeaderName const & header )
        {
            if ( cacheHit_ )
                return;
            includedHeaders_.push_back( header );
        }

        void addStuff( std::shared_ptr<Cache::CacheEntry> const & cacheEntry, bool ignoreHeaders )
        {
            std::set_difference( cacheEntry->usedMacros().begin(), cacheEntry->usedMacros().end(),
                definedMacros_.begin(), definedMacros_.end(),
                std::inserter( usedMacros_, usedMacros_.end() ) );

            headerContent_.push_back( cacheEntry );
            if ( !ignoreHeaders )
                includedHeaders_.push_back( cacheEntry );
        }

        void addHeaders( Headers const & headers )
        {
            std::copy( headers.begin(), headers.end(),
                std::inserter( includedHeaders_, includedHeaders_.begin() ) );
        }

        Macros const & usedMacros() const { return cacheHit_ ? cacheHit_->usedMacros() : usedMacros_; }
        HeaderContent const & headerContent() const { return cacheHit_ ? cacheHit_->headerContent() : headerContent_; }
        Headers const & includedHeaders() const { return includedHeaders_; }
        HeaderName const & header() { return header_; }

        std::shared_ptr<Cache::CacheEntry> addToCache( Cache &, clang::FileEntry const * file, clang::SourceManager & ) const;

        std::shared_ptr<Cache::CacheEntry> const & cacheHit() const { return cacheHit_; }

    private:
        HeaderName header_;
        std::shared_ptr<Cache::CacheEntry> cacheHit_;
        Macros usedMacros_;
        Macros definedMacros_;
        HeaderContent headerContent_;
        Headers includedHeaders_;
    };
    typedef std::vector<HeaderCtx> HeaderCtxStack;

    HeaderCtxStack const & headerCtxStack() const { return headerCtxStack_; }
    HeaderCtxStack       & headerCtxStack()       { return headerCtxStack_; }

    bool cacheDisabled() const { return cache_ == 0; }
    Cache const & cache() const { return *cache_; }
    Cache       & cache()       { return *cache_; }

    clang::Preprocessor & preprocessor() const { return preprocessor_; }
    clang::SourceManager & sourceManager() const;

    llvm::StringRef macroDefFromSourceLocation( clang::MacroDirective const * def );

private:
    llvm::OwningPtr<clang::HeaderSearch> headerSearch_;
    clang::Preprocessor & preprocessor_;
    HeaderCtxStack headerCtxStack_;
    Cache * cache_;
    std::shared_ptr<Cache::CacheEntry> cacheHit_;
    std::vector<std::shared_ptr<Cache::CacheEntry> > cacheEntriesUsed_;
    std::vector<clang::FileEntry const *> fileStack_;
};


//------------------------------------------------------------------------------
#endif