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
    struct HeaderCtx
    {
    public:
        explicit HeaderCtx( HeaderFile const & header, CacheEntryPtr const & cacheHit, clang::Preprocessor const & preprocessor )
            :
            header_( header ),
            cacheHit_( cacheHit ),
            preprocessor_( preprocessor ),
            includeDepth_( 0 )
        {
            if ( cacheHit_ )
                includedHeaders_.push_back( cacheHit );
        }

        void macroUsed( llvm::StringRef macroName, MacroState const & macroState )
        {
            assert( !fromCache() );
            // Macro is marked as 'used' in this header only if it was not also
            // defined here.
            if ( definedHere_.find( macroName ) == definedHere_.end() )
                usedMacros_.insert( std::make_pair( macroName, macroState.macroValue( macroName ) ) );
        }

        void macroDefined( llvm::StringRef macroName, llvm::StringRef macroDef )
        {
            assert( !fromCache() );
            Macro const macro( createMacro( macroName, macroDef ) );
            headerContent_.push_back( std::make_pair( MacroUsage::defined, macro ) );
            MacroNames::const_iterator const undefIter( undefinedHere_.find( macroName ) );
            if ( undefIter != undefinedHere_.end() )
                undefinedHere_.erase( undefIter );
            else
                definedHere_.insert( macroName );
        }

        void macroUndefined( llvm::StringRef macroName )
        {
            assert( !fromCache() );
            Macro const macro( createMacro( macroName, undefinedMacroValue() ) );
            headerContent_.push_back( std::make_pair( MacroUsage::undefined, macro ) );
            MacroNames::const_iterator const defIter( definedHere_.find( macroName ) );
            if ( defIter != definedHere_.end() )
            {
                usedMacros_.erase( macro.first );
                definedHere_.erase( defIter );
            }
            else
            {
                undefinedHere_.insert( macroName );
            }
        }

        void addHeader( HeaderFile const & header )
        {
            assert ( !fromCache() );
            includedHeaders_.push_back( header );
        }

        void propagateChildInfo( HeaderCtx const & child, bool ignoreHeaders )
        {
            Macros::const_iterator       cacheIter = child.usedMacros().begin();
            Macros::const_iterator const cacheEnd = child.usedMacros().end();
            MacroNames::const_iterator       definedIter = definedHere_.begin();
            MacroNames::const_iterator const definedEnd = definedHere_.end();
            while ( cacheIter != cacheEnd && definedIter != definedEnd )
            {
                int const compareResult = definedIter->compare( macroName( *cacheIter ) );
                if ( compareResult < 0 )
                {
                    usedMacros_.insert( *cacheIter );
                    ++cacheIter;
                }
                else if ( compareResult > 0 )
                {
                    ++definedIter;
                }
                else
                {
                    ++cacheIter;
                    ++definedIter;
                }
            }
            std::copy( cacheIter, cacheEnd,
                std::inserter( usedMacros_, usedMacros_.begin() ) );

            std::copy( child.headerContent().begin(), child.headerContent().end(), std::back_inserter( headerContent_ ) );
            if ( !ignoreHeaders )
                std::copy( child.includedHeaders().begin(), child.includedHeaders().end(), std::back_inserter( includedHeaders_ ) );
            includeDepth_ = std::max<unsigned>( includeDepth_, child.includeDepth_ + 1 );
        }

        void propagateChildInfo( CacheEntryPtr const & cacheEntry, bool ignoreHeaders )
        {
            Macros::const_iterator       cacheIter = cacheEntry->usedMacros().begin();
            Macros::const_iterator const cacheEnd = cacheEntry->usedMacros().end();
            MacroNames::const_iterator       definedIter = definedHere_.begin();
            MacroNames::const_iterator const definedEnd = definedHere_.end();
            while ( cacheIter != cacheEnd && definedIter != definedEnd )
            {
                int const compareResult = definedIter->compare( macroName( *cacheIter ) );
                if ( compareResult < 0 )
                {
                    usedMacros_.insert( *cacheIter );
                    ++cacheIter;
                }
                else if ( compareResult > 0 )
                {
                    ++definedIter;
                }
                else
                {
                    ++cacheIter;
                    ++definedIter;
                }
            }
            std::copy( cacheIter, cacheEnd,
                std::inserter( usedMacros_, usedMacros_.begin() ) );

            headerContent_.push_back( cacheEntry );
            if ( !ignoreHeaders )
                includedHeaders_.push_back( cacheEntry );
            includeDepth_ = std::max( includeDepth_, cacheEntry->includeDepth() + 1 );
        }

        Macros const & usedMacros() const { return cacheHit_ ? cacheHit_->usedMacros() : usedMacros_; }
        HeaderContent const & headerContent() const { return cacheHit_ ? cacheHit_->headerContent() : headerContent_; }
        Headers const & includedHeaders() const { return includedHeaders_; }
        HeaderFile const & header() { return header_; }
        unsigned includeDepth() const { return includeDepth_; }

        CacheEntryPtr addToCache( Cache &, clang::FileEntry const * file, clang::SourceManager & ) const;

        CacheEntryPtr const & cacheHit() const { return cacheHit_; }

        bool fromCache() const { return cacheHit_; }

    private:
        typedef boost::container::flat_set<llvm::StringRef> MacroNames;

    private:
        clang::Preprocessor const & preprocessor_;
        HeaderFile header_;
        CacheEntryPtr cacheHit_;
        Macros usedMacros_;
        MacroNames definedHere_;
        MacroNames undefinedHere_;
        HeaderContent headerContent_;
        Headers includedHeaders_;
        unsigned includeDepth_;
    };
    typedef std::vector<HeaderCtx> HeaderCtxStack;

    HeaderCtxStack const & headerCtxStack() const { return headerCtxStack_; }
    HeaderCtxStack       & headerCtxStack()       { return headerCtxStack_; }

    bool cacheDisabled() const { return cache_ == 0; }
    Cache      const & cache() const { return *cache_; }
    Cache            & cache()       { return *cache_; }
    MacroState const & macroState() const { return macroState_; }
    MacroState       & macroState()       { return macroState_; }

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
    MacroState macroState_;
};


//------------------------------------------------------------------------------
#endif