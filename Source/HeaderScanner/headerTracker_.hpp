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

    explicit HeaderTracker( clang::Preprocessor & preprocessor, std::tuple<clang::HeaderSearch *, clang::HeaderSearch *, clang::HeaderSearch *> headerSearch, Cache * cache )
        :
        relativeHeaderSearch_( std::get<0>( headerSearch ) ),
        userHeaderSearch_( std::get<1>( headerSearch ) ),
        systemHeaderSearch_( std::get<2>( headerSearch ) ),
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
            preprocessor_( preprocessor )
        {
            if ( cacheHit_ )
                includedHeaders_.push_back( cacheHit );
        }

        void macroUsed( llvm::StringRef macroName, MacroState const & macroState )
        {
            assert( !fromCache() );
            if ( definedMacroNames_.find( macroName ) == definedMacroNames_.end() )
                usedMacros_.insert( std::make_pair( macroName, macroState.macroValue( macroName ) ) );
        }

        void macroDefined( llvm::StringRef macroName, llvm::StringRef macroDef )
        {
            assert( !fromCache() );
            MacroRef const macro( std::make_pair( macroName, macroDef ) );
            headerContent_.push_back( std::make_pair( MacroUsage::defined, macroFromMacroRef( macro ) ) );
            definedMacroNames_.insert( macroName );
        }

        void macroUndefined( llvm::StringRef macroName )
        {
            assert( !fromCache() );
            MacroRef const macro( std::make_pair( macroName, undefinedMacroValue() ) );
            headerContent_.push_back( std::make_pair( MacroUsage::undefined, macroFromMacroRef( macro ) ) );
        }

        void addHeader( HeaderFile const & header )
        {
            assert ( !fromCache() );
            includedHeaders_.push_back( header );
        }

        void addStuff( CacheEntryPtr const & cacheEntry, bool ignoreHeaders )
        {
            Macros::const_iterator       cacheIter = cacheEntry->usedMacros().begin();
            Macros::const_iterator const cacheEnd = cacheEntry->usedMacros().end();
            DefinedMacroNames::const_iterator       definedIter = definedMacroNames_.begin();
            DefinedMacroNames::const_iterator const definedEnd = definedMacroNames_.end();
            while ( cacheIter != cacheEnd && definedIter != definedEnd )
            {
                int const compareResult = definedIter->compare( macroName( *cacheIter ) );
                if ( compareResult < 0 )
                {
                    usedMacros_.insert( macroRefFromMacro( *cacheIter ) );
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
            std::transform( cacheIter, cacheEnd,
                std::inserter( usedMacros_, usedMacros_.begin() ),
                []( Macro const & macro )
                {
                    return macroRefFromMacro( macro );
                }
            );

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
        HeaderFile const & header() { return header_; }

        CacheEntryPtr addToCache( Cache &, clang::FileEntry const * file, clang::SourceManager & ) const;

        CacheEntryPtr const & cacheHit() const { return cacheHit_; }

        bool fromCache() const { return cacheHit_; }

    private:
        typedef boost::container::flat_set<llvm::StringRef> DefinedMacroNames;

    private:
        clang::Preprocessor const & preprocessor_;
        HeaderFile header_;
        CacheEntryPtr cacheHit_;
        MacroRefs usedMacros_;
        DefinedMacroNames definedMacroNames_;
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
    typedef llvm::SmallString<1024> PathPart;
    typedef std::tuple<clang::FileEntry const *, HeaderLocation::Enum, PathPart, PathPart> IncludeStackEntry;
    typedef std::vector<IncludeStackEntry> IncludeStack;

private:
    llvm::OwningPtr<clang::HeaderSearch> relativeHeaderSearch_;
    llvm::OwningPtr<clang::HeaderSearch> userHeaderSearch_;
    llvm::OwningPtr<clang::HeaderSearch> systemHeaderSearch_;
    clang::Preprocessor & preprocessor_;
    HeaderCtxStack headerCtxStack_;
    Cache * cache_;
    CacheEntryPtr cacheHit_;
    IncludeStack fileStack_;
    MacroState macroState_;
};


//------------------------------------------------------------------------------
#endif