//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef headerTracker_HPP__A726F821_9CFA_4C46_838A_EDF69E6E6DF3
#define headerTracker_HPP__A726F821_9CFA_4C46_838A_EDF69E6E6DF3
//------------------------------------------------------------------------------
#include "headerScanner_.hpp"

#include "headerCache_.hpp"
#include "utility_.hpp"

#include <llvm/ADT/SmallString.h>

#include <deque>
#include <fstream>
#include <mutex>
#include <string>
#include <set>
#include <unordered_set>
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

struct HeaderCtx
{
private:
    HeaderCtx( HeaderCtx const & );
    HeaderCtx & operator=( HeaderCtx const & );

private:
    clang::Preprocessor const & preprocessor_;
    clang::FileEntry const * replacement_;
    HeaderCtx * parent_;
    CacheEntryPtr cacheHit_;
    MacroState macroState_;
    IndexedUsedMacros usedHere_;
    Headers includedHeaders_;

public:
    HeaderCtx( clang::FileEntry const * replacement,
        CacheEntryPtr const & cacheHit,
        clang::Preprocessor const & preprocessor
    )
        :
        preprocessor_( preprocessor ),
        replacement_( replacement ),
        parent_( 0 ),
        cacheHit_( cacheHit )
    {
    }

    void setParent( HeaderCtx * parent )
    {
        parent_ = parent;
    }

    HeaderCtx * parent() const { return parent_; }

    void macroUsed( MacroName macroName )
    {
        assert( !fromCache() );
        // Macro is marked as 'used' in this header only if it was neither
        // defined nor undefined here.
        if ( macroState_.find( macroName ) == macroState_.end() )
            usedHere_.addMacro( macroName, [this]( MacroName name )
            {
                return getMacroValue( name );
            } );
    }

    void macroDefined( MacroName macroName, MacroValue macroValue )
    {
        assert( !fromCache() );
        macroState_.defineMacro( macroName, macroValue );
    }

    void macroUndefined( MacroName macroName )
    {
        assert( !fromCache() );
        macroState_.undefineMacro( macroName );
    }

    MacroValue getMacroValue( MacroName name ) const
    {
        MacroState::const_iterator const stateIter( macroState_.find( name ) );
        if ( stateIter != macroState_.end() )
            return stateIter->second;
        return parent_
            ? parent_->getMacroValue( name )
            : undefinedMacroValue
        ;
    }

    void addHeader( Header const & header )
    {
        assert( !fromCache() );
        includedHeaders_.insert( header );
    }

    void propagateToParent() const
    {
        assert( parent_ );
        assert( !parent_->fromCache() );

        forEachUsedMacro( [=]( UsedMacros::value_type const & usedMacro )
        {
            parent_->macroUsed( usedMacro.first, usedMacro.second );
        });

        parent_->macroState_.merge( macroState() );

        std::copy
        (
            includedHeaders().begin(),
            includedHeaders().end  (),
            std::inserter( parent_->includedHeaders(),
                parent_->includedHeaders().begin() )
        );
    }

    void addToCache( Cache &, std::size_t const searchPathId, clang::FileEntry const * );

    template <typename Func>
    void forEachUsedMacro( Func f ) const
    {
        cacheHit_
            ? cacheHit_->forEachUsedMacro( f )
            : usedHere_.forEachUsedMacro( f )
        ;
    }


    CacheEntryPtr const & cacheHit() const { return cacheHit_; }
    MacroState const & macroState() const { return cacheHit_ ? cacheHit_->macroState() : macroState_; }
    Headers       & includedHeaders()       { assert( !fromCache() ); return includedHeaders_; }
    Headers const & includedHeaders() const { return cacheHit_ ? cacheHit_->headers() : includedHeaders_; }

    bool fromCache() const { return cacheHit_.get() != 0; }
    clang::FileEntry const * replacement() const { return replacement_; }

private:
    void macroUsed( MacroName macroName, MacroValue macroValue )
    {
        assert( !fromCache() );
        // Macro is marked as 'used' in this header only if it was neither
        // defined nor undefined here.
        if ( macroState_.find( macroName ) == macroState_.end() )
            usedHere_.addMacro( macroName, macroValue );
    }
};

class HeaderTracker
{
private:
    typedef std::vector<HeaderWithFileEntry> IncludeStack;
    typedef std::map<clang::FileEntry const *, CacheEntryPtr> UsedCacheEntries;

    clang::Preprocessor & preprocessor_;
    std::size_t searchPathId_;
    HeaderCtx * pCurrentCtx_;
    clang::FileEntry const * replacement_;
    Cache * cache_;
    CacheEntryPtr cacheHit_;
    IncludeStack fileStack_;
    UsedCacheEntries usedCacheEntries_;

public:
    explicit HeaderTracker( clang::Preprocessor & preprocessor, std::size_t searchPathId, Cache * cache )
        :
        preprocessor_( preprocessor ),
        searchPathId_( searchPathId ),
        pCurrentCtx_( 0 ),
        replacement_( 0 ),
        cache_( cache )
    {
    }

    void enterSourceFile( clang::FileEntry const *, llvm::StringRef fileName );
    void exitSourceFile( Headers & );

    void inclusionDirective( llvm::StringRef searchPath,
        llvm::StringRef relativePath,
        llvm::StringRef fileName,
        bool isAngled,
        clang::FileEntry const * );
    void replaceFile( clang::FileEntry const * & fileEntry );
    void headerSkipped();
    void enterHeader();
    void leaveHeader();
    void pragmaOnce();

    void macroUsed( llvm::StringRef name );
    void macroDefined( llvm::StringRef name, clang::MacroDirective const * def );
    void macroUndefined( llvm::StringRef name, clang::MacroDirective const * def );

private:
    void pushHeaderCtx( std::unique_ptr<HeaderCtx> headerCtx )
    {
        headerCtx->setParent( pCurrentCtx_ );
        pCurrentCtx_ = headerCtx.release();
    }

    void popHeaderCtx()
    {
        HeaderCtx * result = pCurrentCtx_;
        pCurrentCtx_ = pCurrentCtx_->parent();
        result->setParent( 0 );
        delete result;
    }

    HeaderCtx & currentHeaderCtx()
    {
        assert( hasCurrentHeaderCtx() );
        return *pCurrentCtx_;
    }

    bool hasCurrentHeaderCtx() const { return pCurrentCtx_ != 0; }

    bool cacheDisabled() const { return cache_ == 0; }

    Cache const & cache() const { return *cache_; }
    Cache       & cache()       { return *cache_; }

    bool isViableForCache( HeaderCtx const &, clang::FileEntry const * ) const;

public:
    clang::Preprocessor & preprocessor() const { return preprocessor_; }
    clang::SourceManager & sourceManager() const;

private:
    MacroName macroForPragmaOnce( llvm::sys::fs::UniqueID const & );
};


//------------------------------------------------------------------------------
#endif