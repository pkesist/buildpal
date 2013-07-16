//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef headerTracker_HPP__A726F821_9CFA_4C46_838A_EDF69E6E6DF3
#define headerTracker_HPP__A726F821_9CFA_4C46_838A_EDF69E6E6DF3
//------------------------------------------------------------------------------
#include "headerScanner_.hpp"

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

typedef std::pair<llvm::StringRef, llvm::StringRef> Macro;
typedef std::set<Macro> MacroSet;
struct MacroUsage { enum Enum { macroUsed, macroDefined, macroUndefined }; };
typedef std::map<llvm::StringRef, llvm::StringRef> MacroMap;
typedef std::pair<MacroUsage::Enum, Macro> MacroWithUsage;
typedef std::vector<MacroWithUsage> MacroUsages;
typedef std::pair<llvm::StringRef, llvm::StringRef> Header;
typedef std::set<Header> Headers;

class Cache
{
public:
    struct CacheEntry
    {
        CacheEntry
        (
            MacroMap const & definedMacrosp,
            MacroMap const & undefinedMacrosp,
            Headers const & headersp
        ) : 
            fileEntry_( 0 ),
            overridden_( false ),
            definedMacros( definedMacrosp ),
            undefinedMacros( undefinedMacrosp ),
            headers( headersp )
        {}

        clang::FileEntry const * getFileEntry( clang::SourceManager & );
        void releaseFileEntry( clang::SourceManager & );

    private:
        clang::FileEntry const * fileEntry_;
        bool overridden_;

    public:
        MacroMap definedMacros;
        MacroMap undefinedMacros;
        Headers headers;
    };
    struct HeaderInfo : public std::map<MacroSet, CacheEntry> {};
    typedef HeaderInfo::value_type CacheHit;

    template <typename HeadersList>
    void addEntry
    (
        clang::FileEntry const * file,
        MacroSet const & macros,
        MacroMap const & definedMacros,
        MacroMap const & undefinedMacros,
        HeadersList const & headers
    )
    {
        // Clone all stringrefs to this cache's flyweight.
        headersInfo()[ file ].insert(
            std::make_pair( cloneMacros( macros ), CacheEntry( cloneMacros( definedMacros ), cloneMacros( undefinedMacros ), cloneHeaders( headers ) ) ) );
    }

    HeaderInfo::value_type * findEntry
    ( 
        clang::FileEntry const * file,
        clang::Preprocessor const & preprocessor
    );

private:
    // Poor man's flyweight.
    llvm::StringRef cloneStr( llvm::StringRef x )
    {
        std::pair<std::set<std::string>::iterator, bool> insertResult( flyweight_.insert( x ) );
        return llvm::StringRef( insertResult.first->data(), insertResult.first->size() );
    }

    template <typename MacroList>
    MacroList cloneMacros( MacroList const & macros )
    {
        MacroList result;
        for ( MacroList::const_iterator iter( macros.begin() ); iter != macros.end(); ++iter )
        {
            Macro const macro( cloneStr( iter->first ), cloneStr( iter->second ) );
            result.insert( macro );
        }
        return result;
    }

    template <typename HeadersList>
    Headers cloneHeaders( HeadersList const & headers )
    {
        Headers result;
        for ( HeadersList::const_iterator iter( headers.begin() ); iter != headers.end(); ++iter )
        {
            Header const header( cloneStr( iter->first ), cloneStr( iter->second ) );
            result.insert( header );
        }
        return result;
    }

private:
    struct HeadersInfo : public std::map<clang::FileEntry const *, HeaderInfo> {};

    HeadersInfo const & headersInfo() const { return headersInfo_; }
    HeadersInfo       & headersInfo()       { return headersInfo_; }

private:
    HeadersInfo headersInfo_;
    std::set<std::string> flyweight_;
};

class HeaderTracker
{
public:
    typedef Preprocessor::HeaderRef Header;
    typedef Preprocessor::HeaderRefs Headers;
    typedef PreprocessingContext::IgnoredHeaders IgnoredHeaders;

    explicit HeaderTracker( clang::SourceManager & sm )
        : sourceManager_( sm ), preprocessor_( 0 ), cacheHit_( 0 )
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
            MacroMap::iterator const iter( definedMacros_.find( macro.first ) );
            if ( iter == definedMacros_.end() )
                usedMacros_.insert( macro );
        }

        void macroDefined( Macro const & macro )
        {
            definedMacros_.insert( macro );
        }

        void macroUndefined( Macro const & macro )
        {
            MacroMap::iterator const iter( definedMacros_.find( macro.first ) );
            if ( iter != definedMacros_.end() )
            {
                usedMacros_.erase( *iter );
                definedMacros_.erase( iter );
            }
            else
            {
                undefinedMacros_.insert( macro );
            }
        }

        void addHeader( Header const & header )
        {
            includedHeaders_.insert( header );
        }

        template <typename Headers>
        void addStuff( MacroSet const & used, MacroMap const & defined, MacroMap const & undefined, Headers const * headers )
        {
            struct MacroUsed
            {
                HeaderCtx & ctx_;

                MacroUsed( HeaderCtx & ctx ) : ctx_( ctx ) {}
                void operator()( Macro const & macro )
                {
                    ctx_.macroUsed( macro );
                }
            } macroUsed( *this );
            std::for_each( used.begin(), used.end(), macroUsed );

            struct MacroDefined
            {
                HeaderCtx & ctx_;

                MacroDefined( HeaderCtx & ctx ) : ctx_( ctx ) {}
                void operator()( Macro const & macro )
                {
                    ctx_.macroDefined( macro );
                }
            } macroDefined( *this );
            std::for_each( defined.begin(), defined.end(), macroDefined );

            struct MacroUndefined
            {
                HeaderCtx & ctx_;

                MacroUndefined( HeaderCtx & ctx ) : ctx_( ctx ) {}
                void operator()( Macro const & macro )
                {
                    ctx_.macroUndefined( macro );
                }
            } macroUndefined( *this );
            std::for_each( undefined.begin(), undefined.end(), macroUndefined );

            if ( headers )
            {
                std::copy( headers->begin(), headers->end(),
                    std::inserter( includedHeaders_, includedHeaders_.begin() ) );
            }
        }

        MacroSet const & usedMacros() const { return usedMacros_; }
        MacroMap const & definedMacros() const { return definedMacros_; }
        MacroMap const & undefinedMacros() const { return undefinedMacros_; }
        Headers const & includedHeaders() const { return includedHeaders_; }
        Header const & header() { return header_; }

        void addToCache( Cache &, clang::FileEntry const * file, clang::SourceManager & ) const;

    private:
        Header header_;
        
        typedef std::map<llvm::StringRef, llvm::StringRef> MacroMap;

        MacroSet usedMacros_;
        MacroMap definedMacros_;
        MacroMap undefinedMacros_;
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
    Cache cache_;
    Cache::CacheHit * cacheHit_;
    std::vector<clang::FileEntry const *> fileStack_;
};


//------------------------------------------------------------------------------
#endif