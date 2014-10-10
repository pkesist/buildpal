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

class MacroState;

namespace clang
{
    class Preprocessor;
    class SourceManager;
    class FileEntry;
    class MacroDirective;
    class HeaderSearch;
}

typedef std::unordered_set<MacroName> MacroSet;

class HeaderCtx
{
private:
    HeaderCtx( HeaderCtx const & );
    HeaderCtx & operator=( HeaderCtx const & );

private:
    clang::Preprocessor const & preprocessor_;
    clang::FileEntry const * original_;
    clang::FileEntry const * replacement_;
    HeaderCtx * parent_;
    CacheEntryPtr cacheHit_;
    MacroState & macroState_;
    IndexedUsedMacros usedHere_;
    MacroSet changedHere_;
    Headers includedHeaders_;

public:
    HeaderCtx(
        MacroState & macroState,
        clang::FileEntry const * original,
        clang::FileEntry const * replacement,
        CacheEntryPtr const & cacheHit,
        HeaderCtx * parent,
        clang::Preprocessor const & preprocessor
    )
        :
        preprocessor_( preprocessor ),
        original_( original ),
        replacement_( replacement ),
        parent_( parent ),
        cacheHit_( cacheHit ),
        macroState_( macroState )
    {
    }

    HeaderCtx * parent() const { return parent_; }

    void macroUsed( MacroName const & macroName )
    {
        assert( !fromCache() );
        // Macro is marked as 'used' in this header only if it was not changed
        // here
        if ( changedHere_.find( macroName ) == changedHere_.end() )
            usedHere_.addMacro( macroName, [this]( MacroName const & name )
            {
                return getMacroValue( name );
            } );
    }

    void macroDefined( MacroName const & macroName, MacroValue const & macroValue )
    {
        assert( !fromCache() );
        macroState_.defineMacro( macroName, macroValue );
        changedHere_.insert( macroName );
    }

    void macroUndefined( MacroName const & macroName )
    {
        assert( !fromCache() );
        macroState_.undefineMacro( macroName );
        changedHere_.insert( macroName );
    }

    MacroValue getMacroValue( MacroName const & name ) const
    {
        MacroValue value;
        return macroState_.getMacroValue( name, value ) ? value : undefinedMacroValue;
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

        if ( fromCache() )
        {
            cacheHit_->forEachUsedMacro( [this]( Macro const & macro )
            {
                parent_->macroUsed( macro.first, macro.second );
            });

            cacheHit_->macroState().forEachMacro([this]( Macro const & macro )
            {
                parent_->changedHere_.insert( macro.first );
                macroState_.defineMacro( macro.first, macro.second );
            });
        }
        else
        {
            for ( Macro const & macro : usedHere_ )
            {
                parent_->macroUsed( macro.first, macro.second );
            }
            parent_->changedHere_.insert( changedHere_.begin(), changedHere_.end() );
        }

        std::copy
        (
            includedHeaders().begin(),
            includedHeaders().end  (),
            std::inserter( parent_->includedHeaders(),
                parent_->includedHeaders().begin() )
        );
    }

    bool isViableForCache() const
    {
        // Headers which have overridden content are poor candidates for caching.
        // Currently these are cache-generated headers themselves, and empty
        // header used to implement #pragma once support.
        if ( replacement_ != 0 )
            return false;
        // Only cache headers which use a *sane* amount of macros.
        return usedHere_.size() < 1024;
    }

    void addToCache( Cache &, std::size_t const searchPathId, clang::FileEntry const * );

    CacheEntryPtr const & cacheHit() const { return cacheHit_; }
    Headers       & includedHeaders()       { assert( !fromCache() ); return includedHeaders_; }
    Headers const & includedHeaders() const { return cacheHit_ ? cacheHit_->headers() : includedHeaders_; }

    bool fromCache() const { return cacheHit_.get() != 0; }
    clang::FileEntry const * replacement() const { return replacement_; }

private:
    void macroUsed( MacroName const & macroName, MacroValue const & macroValue )
    {
        assert( !fromCache() );
        // Macro is marked as 'used' in this header only if it was not changed
        // here.
        if ( changedHere_.find( macroName ) == changedHere_.end() )
            usedHere_.addMacro( macroName, macroValue );
    }
};

#ifdef DEBUG_HEADERS
extern std::ofstream logging_stream;
#endif

class ConditionStack
{
private:
    typedef std::vector<llvm::StringRef> Macros;

    struct Condition
    {
        Macros macros;
        clang::SourceLocation lastLocation;
        bool lastBranchTaken;
        bool anyBranchTaken;

        explicit Condition( clang::SourceLocation loc )
            : lastLocation( loc ), lastBranchTaken( false ),
              anyBranchTaken( false )
        {}
    };

    typedef std::vector<Condition> Conditions;

    Macros macros;
    Conditions conditions;
    clang::Preprocessor & preprocessor_;
    std::function<void (llvm::StringRef)> macroUsedCallback_;
    mutable llvm::SmallString<1024> tmpBuf_;
    
public:
    template <typename F>
    ConditionStack( clang::Preprocessor & preprocessor, F & macroUsedCallback )
        :
        preprocessor_( preprocessor ),
        macroUsedCallback_( macroUsedCallback )
    {
    }

    void addMacro( llvm::StringRef name )
    {
        macros.push_back( name );
    }

    void commit()
    {
        for ( Condition & condition : conditions )
        {
            std::for_each( condition.macros.begin(), condition.macros.end(), macroUsedCallback_ );
        }
        conditions.clear();

        std::for_each( macros.begin(), macros.end(), macroUsedCallback_ );
        macros.clear();
    }

    void ifDirective( clang::SourceLocation, bool taken );
    void elifDirective( clang::SourceLocation, bool taken );
    void elseDirective( clang::SourceLocation );
    void endifDirective( clang::SourceLocation );

    bool empty() const { return conditions.empty(); }

private:
    bool skippable( clang::SourceLocation startLoc, clang::SourceLocation endLoc ) const;
    Condition & condition() { assert( !empty() ); return conditions.back(); }

    bool lastConditionSkippable( clang::SourceLocation loc );
};

struct HeaderWithFileEntry
{
private:
    HeaderWithFileEntry( HeaderWithFileEntry const & ); // = delete 
    HeaderWithFileEntry & operator=( HeaderWithFileEntry const & ); // = delete

public:
    HeaderWithFileEntry( Dir const & dirParam, HeaderName const & nameParam, bool relativeParam,
        clang::FileEntry const * fileParam ) : dir( dirParam ),
        name( nameParam ), relative( relativeParam ),
        file( fileParam )
    {
    }


    HeaderWithFileEntry( HeaderWithFileEntry && h )
        :
        dir( std::move( h.dir ) ),
        name( std::move( h.name ) ),
        relative( h.relative ),
        file( h.file ),
        pHeaderCtx( std::move( h.pHeaderCtx ) )
    {
    }

    HeaderWithFileEntry & operator=( HeaderWithFileEntry && h )
    {
        dir = std::move( h.dir );
        name = std::move( h.name );
        relative = h.relative;
        file = h.file;
        pHeaderCtx = std::move( h.pHeaderCtx );
    }

public:
    Dir dir;
    HeaderName name;
    bool relative;
    clang::FileEntry const * file;
    std::unique_ptr<HeaderCtx> pHeaderCtx;

    Header makeHeader() const;
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
    MacroState macroState_;
    UsedCacheEntries usedCacheEntries_;
    std::vector<llvm::StringRef> currentUsedMacros_;
    ConditionStack conditionStack_;

public:
    explicit HeaderTracker( clang::Preprocessor & preprocessor, std::size_t searchPathId, Cache * cache );

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

    void ifDirective( clang::SourceLocation loc, bool taken )
    {
        conditionStack_.ifDirective( loc, taken );
    }

    void elifDirective( clang::SourceLocation loc, bool taken )
    {
        conditionStack_.elifDirective( loc, taken );
    }

    void elseDirective( clang::SourceLocation loc )
    {
        conditionStack_.elseDirective( loc );
    }

    void endifDirective( clang::SourceLocation loc )
    {
        conditionStack_.endifDirective( loc );
    }

    void macroUsed( llvm::StringRef name );
    void macroDefined( llvm::StringRef name, clang::MacroDirective const * def );
    void macroUndefined( llvm::StringRef name, clang::MacroDirective const * def );

private:
    void commitMacros()
    {
        conditionStack_.commit();
    }

    void enterFile();
    void exitFile();

    HeaderCtx & currentHeaderCtx()
    {
        assert( hasCurrentHeaderCtx() );
        return *pCurrentCtx_;
    }

    bool hasCurrentHeaderCtx() const { return pCurrentCtx_ != 0; }

    bool cacheDisabled() const { return cache_ == 0; }

    Cache const & cache() const { return *cache_; }
    Cache       & cache()       { return *cache_; }

public:
    clang::Preprocessor & preprocessor() const { return preprocessor_; }
    clang::SourceManager & sourceManager() const;
};


//------------------------------------------------------------------------------
#endif