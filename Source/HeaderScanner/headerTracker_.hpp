//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef headerTracker_HPP__A726F821_9CFA_4C46_838A_EDF69E6E6DF3
#define headerTracker_HPP__A726F821_9CFA_4C46_838A_EDF69E6E6DF3
//------------------------------------------------------------------------------
#include "headerScanner_.hpp"

#include "headerCache_.hpp"
#include "utility_.hpp"

#include <boost/container/flat_set.hpp>

#include <llvm/ADT/SmallString.h>

#include <deque>
#include <fstream>
#include <mutex>
#include <string>
#include <set>
#include <vector>

#include <windows.h>
#undef SearchPath
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
public:
    explicit HeaderCtx( Header const & header, CacheEntryPtr const & cacheHit, clang::Preprocessor const & preprocessor, HeaderCtx * parent )
        :
        header_( header ),
        cacheHit_( cacheHit ),
        preprocessor_( preprocessor ),
        parent_( parent )
    {
    }

    void macroUsed( llvm::StringRef macroName )
    {
        assert( !fromCache() );
        // Macro is marked as 'used' in this header only if it was not also
        // defined here.
        if ( macroState_.find( macroName ) == macroState_.end() )
            usedHere_.insert( macroName );
    }

    void macroDefined( llvm::StringRef macroName, llvm::StringRef macroValue )
    {
        assert( !fromCache() );
        macroState_.defineMacro( macroName, macroValue );
    }

    void macroUndefined( llvm::StringRef macroName )
    {
        assert( !fromCache() );
        if ( macroState_.find( macroName ) != macroState_.end() )
            macroState_.undefineMacro( macroName );
        else
            undefinedHere_.insert( macroName );
    }

    llvm::StringRef getMacroValue( llvm::StringRef name ) const
    {
        MacroState::const_iterator const stateIter( macroState_.find( name ) );
        if ( stateIter != macroState_.end() )
            return stateIter->getValue();
        if ( undefinedHere_.find( name ) != undefinedHere_.end() )
            return undefinedMacroValue();
        return parent_
            ? parent_->getMacroValue( name )
            : undefinedMacroValue()
        ;
    }

    Macros createCacheKey() const
    {
        assert( parent_ );
        Macros result;
        std::transform(
            usedHere_.begin(),
            usedHere_.end(),
            std::inserter( result, result.begin() ),
            [&, this]( llvm::StringRef macroName )
            {
                // When creating cache key we must use old macro values, as they
                // were in parent at the time of inclusion.
                return createMacro( macroName, parent_->getMacroValue( macroName ) );
            }
        );
        return result;
    }

    HeaderContent createHeaderContent() const
    {
        HeaderContent headerContent;
        for ( llvm::StringRef undefinedMacro : undefinedHere_ )
        {
            headerContent.push_back( std::make_pair( MacroUsage::undefined, createMacro( undefinedMacro, undefinedMacroValue() ) ) );
        }
        for ( MacroState::value_type const & value : macroState_ )
        {
            headerContent.push_back( std::make_pair( MacroUsage::defined, createMacro( value.getKey(), value.getValue() ) ) );
        }
        return headerContent;
    }

    void addHeader( Header const & header )
    {
        assert( !fromCache() );
        includedHeaders_.insert( header );
    }

    void propagateToParent( IgnoredHeaders const & ignoredHeaders, CacheEntryPtr const childCacheEntry )
    {
        assert( parent_ );
        assert( !parent_->fromCache() );

        // First propagate all macros used by child.
        if ( fromCache() )
        {
            for ( Macro const & usedMacro : cacheHit_->usedMacros() )
                parent_->macroUsed( usedMacro.first.get() );

            for ( HeaderEntry const & headerEntry : cacheHit_->headerContent() )
            {
                if ( headerEntry.first == MacroUsage::defined )
                    parent_->macroDefined( macroName( headerEntry.second ),
                        macroValue( headerEntry.second ) );
                else
                {
                    assert( headerEntry.first == MacroUsage::undefined );
                    parent_->macroUndefined( macroName( headerEntry.second ) );
                }
            }
        }
        else
        {
            for ( llvm::StringRef usedMacro : usedHere_ )
                parent_->macroUsed( usedMacro );

            // If child header undefined a macro.
            for ( llvm::StringRef undefinedMacro : undefinedHere_ )
            {
                // And did not re-define it.
                if ( macroState_.find( undefinedMacro ) == macroState_.end() )
                    // Undefine it in parent state.
                    parent_->macroUndefined( undefinedMacro );
            }

            // Add all macro definitions from child (including redefinitions)
            // to parent header macro state.
            for ( MacroState::value_type const & entry : macroState_ )
                parent_->macroDefined( entry.getKey(), entry.getValue() );
        }
        
        // Sometimes we do not want to propagate headers upwards. More specifically,
        // if we are in a PCH, headers it includes are not needed as
        // their contents is a part of the compiled PCH.
        if ( ignoredHeaders.find( std::get<1>( parent_->header() ) ) == ignoredHeaders.end() )
        {
            std::copy(
                includedHeaders().begin(),
                includedHeaders().end(),
                std::inserter( parent_->includedHeaders_, parent_->includedHeaders_.begin() )
            );
        }
    }

    Headers const & includedHeaders() const { return includedHeaders_; }
    Header const & header() const { return header_; }

    CacheEntryPtr addToCache( Cache &, clang::FileEntry const * file, clang::SourceManager & ) const;

    CacheEntryPtr const & cacheHit() const { return cacheHit_; }

    bool fromCache() const { return cacheHit_; }

private:
    typedef boost::container::flat_set<llvm::StringRef> MacroNames;

private:
    MacroState macroState_;
    clang::Preprocessor const & preprocessor_;
    HeaderCtx * parent_;
    Header header_;
    CacheEntryPtr cacheHit_;
    MacroNames usedHere_;
    MacroNames definedHere_;
    MacroNames undefinedHere_;
    Headers includedHeaders_;
};

class HeaderTracker
{
public:
    explicit HeaderTracker( clang::Preprocessor & preprocessor, clang::HeaderSearch * headerSearch, Cache * cache )
        :
        headerSearch_( headerSearch ),
        preprocessor_( preprocessor ),
        cache_( cache )
    {
    }

    void enterSourceFile( clang::FileEntry const *, llvm::StringRef dirPart, llvm::StringRef relPart );
    Preprocessor::HeaderRefs exitSourceFile();

    void findFile( llvm::StringRef fileName, bool const isAngled, clang::FileEntry const * & fileEntry );
    void headerSkipped();
    void enterHeader();
    void leaveHeader( IgnoredHeaders const & );

    void macroUsed( llvm::StringRef name, clang::MacroDirective const * def );
    void macroDefined( llvm::StringRef name, clang::MacroDirective const * def );
    void macroUndefined( llvm::StringRef name, clang::MacroDirective const * def );

private:
    typedef std::deque<HeaderCtx> HeaderCtxStack;

    HeaderCtxStack const & headerCtxStack() const { return headerCtxStack_; }
    HeaderCtxStack       & headerCtxStack()       { return headerCtxStack_; }

    bool cacheDisabled() const { return cache_ == 0; }
    Cache      const & cache() const { return *cache_; }
    Cache            & cache()       { return *cache_; }

    bool isViableForCache( HeaderCtx const &, clang::FileEntry const * ) const;

    clang::Preprocessor & preprocessor() const { return preprocessor_; }
    clang::SourceManager & sourceManager() const;

private:
    typedef llvm::SmallString<1024> PathPart;
    typedef std::tuple<clang::FileEntry const *, HeaderLocation::Enum, PathPart, PathPart> IncludeStackEntry;
    typedef std::vector<IncludeStackEntry> IncludeStack;

private:
    llvm::OwningPtr<clang::HeaderSearch> headerSearch_;
    std::vector<std::string> buffers_;
    clang::Preprocessor & preprocessor_;
    HeaderCtxStack headerCtxStack_;
    Cache * cache_;
    CacheEntryPtr cacheHit_;
    IncludeStack fileStack_;
};


//------------------------------------------------------------------------------
#endif