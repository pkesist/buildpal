//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef headerCache_HPP__A615CA5B_F047_45DE_8314_AF96E4F4FF86
#define headerCache_HPP__A615CA5B_F047_45DE_8314_AF96E4F4FF86
//------------------------------------------------------------------------------
#include "contentCache_.hpp"
#include "headerScanner_.hpp"
#include "utility_.hpp"

#include <boost/intrusive_ptr.hpp>
#include <boost/container/list.hpp>
#include <boost/multi_index_container.hpp>
#include <boost/multi_index/composite_key.hpp>
#include <boost/multi_index/hashed_index.hpp>
#include <boost/multi_index/ordered_index.hpp>
#include <boost/thread/lock_algorithms.hpp>
#include <boost/thread/shared_mutex.hpp>
  
#include <llvm/ADT/StringMap.h>
#include <llvm/Support/MemoryBuffer.h>
#include <llvm/Support/raw_ostream.h>

#include <atomic>
#include <list>
#include <set>
#include <string>
#include <tuple>
#include <unordered_map>
#include <unordered_set>
#include <vector>

struct HeaderCtx;

namespace clang
{
    class FileEntry;
}

typedef std::pair<MacroName, MacroValue> Macro;
typedef std::vector<Macro> Macros;

inline Macro createMacro( llvm::StringRef name, llvm::StringRef value )
{
    return std::make_pair( MacroName( name ), MacroValue( value ) );
}

inline llvm::StringRef macroName( Macro const & macro )
{
    return macro.first.get();
}

inline llvm::StringRef macroValue( Macro const & macro )
{
    return macro.second.get();
}

inline llvm::StringRef undefinedMacroValue()
{
    return llvm::StringRef( "", 1 );
}

inline bool isUndefinedMacroValue( llvm::StringRef value )
{
    return value.size() == 1 && *value.data() == '\0';
}

struct MacroUsage { enum Enum { defined, undefined }; };
class CacheEntry;
typedef boost::intrusive_ptr<CacheEntry> CacheEntryPtr;

struct HeaderWithFileEntry
{
    Header header;
    clang::FileEntry const * file;
};


typedef std::pair<MacroUsage::Enum, Macro> HeaderEntry;
typedef std::vector<HeaderEntry> HeaderContent;

struct MacroState : public llvm::StringMap<llvm::StringRef, llvm::BumpPtrAllocator>
{
    llvm::StringRef macroValue( llvm::StringRef macroName ) const
    {
        MacroState::const_iterator const iter( find( macroName ) );
        return iter == end() ? undefinedMacroValue() : iter->getValue() ;
    }

    void defineMacro( llvm::StringRef name, llvm::StringRef value )
    {
        operator[]( name ) = value;
    }

    void undefineMacro( llvm::StringRef name )
    {
        erase( name );
    }
};

void intrusive_ptr_add_ref( CacheEntry * );
void intrusive_ptr_release( CacheEntry * );

typedef llvm::sys::fs::UniqueID FileId;

class CacheEntry
{
private:
    CacheEntry
    (
        FileId fileId,
        std::size_t searchPathId,
        std::string const & uniqueVirtualFileName,
        Macros && usedMacros,
        HeaderContent && headerContent,
        Headers const & headers,
        std::size_t currentTime

    ) :
        refCount_( 0 ),
        searchPathId_( searchPathId ),
        fileId_( fileId ),
        usedMacros_( usedMacros ),
        fileName_( uniqueVirtualFileName ),
        headerContent_( headerContent ),
        headers_( headers ),
        lastTimeHit_( currentTime )
    {
        contentLock_.clear();
    }

public:
    static CacheEntryPtr create
    (
        FileId fileId,
        std::size_t searchPathId,
        std::string const & uniqueVirtualFileName,
        Macros && usedMacros,
        HeaderContent && headerContent,
        Headers const & headers,
        unsigned currentTime
    )
    {
        CacheEntry * result = new CacheEntry
        (
            fileId,
            searchPathId,
            uniqueVirtualFileName,
            std::move( usedMacros ),
            std::move( headerContent ),
            headers,
            currentTime
        );
        return CacheEntryPtr( result );
    }

    clang::FileEntry const * getFileEntry( clang::SourceManager & );
    llvm::MemoryBuffer const * cachedContent();

    Macros        const & usedMacros   () const { return usedMacros_; }
    HeaderContent       & headerContent()       { return headerContent_; }
    HeaderContent const & headerContent() const { return headerContent_; }
    Headers       const & headers      () const { return headers_; }
    FileId fileId() const { return fileId_; }
    std::size_t searchPathId() const { return searchPathId_; }
    std::size_t lastTimeHit() const { return lastTimeHit_; }
    
    void cacheHit( unsigned int currentTime )
    {
        lastTimeHit_ = currentTime;
    }

    std::size_t getRef()
    {
        return refCount_.load( std::memory_order_relaxed );
    }

private:
    void generateContent( std::string & );

    friend void intrusive_ptr_add_ref( CacheEntry * );
    friend void intrusive_ptr_release( CacheEntry * );

    void addRef()
    {
        refCount_.fetch_add( 1, std::memory_order_relaxed );
    }

    void decRef()
    {
        if ( refCount_.fetch_sub( 1, std::memory_order_release ) == 1 )
        {
            std::atomic_thread_fence( std::memory_order_acquire );
            delete this;
        }
    }

private:
    mutable std::atomic<size_t> refCount_;
    FileId fileId_;
    std::size_t searchPathId_;
    std::string fileName_;
    Macros usedMacros_;
    HeaderContent headerContent_;
    Headers headers_;
    std::size_t lastTimeHit_;
    std::atomic_flag contentLock_;
    std::string buffer_;
    llvm::OwningPtr<llvm::MemoryBuffer> memoryBuffer_;
};


inline void intrusive_ptr_add_ref( CacheEntry * c ) { c->addRef(); }
inline void intrusive_ptr_release( CacheEntry * c ) { c->decRef(); }

class Cache
{
public:
    Cache() : counter_( 0 ), fileIdCounter_( 0 ), hits_( 0 ), misses_( 0 ) {}

    CacheEntryPtr addEntry
    (
        llvm::sys::fs::UniqueID const & id,
        std::size_t searchPathId,
        Macros && macros,
        HeaderContent && headerContent,
        Headers const & headers
    );

    CacheEntryPtr findEntry
    (
        llvm::sys::fs::UniqueID const & id,
        std::size_t searchPathId,
        HeaderCtx const &
    );

    std::size_t hits() const { return hits_; }
    std::size_t misses() const { return misses_; }

    void dumpEntry( CacheEntryPtr entry, std::ostream & ostream )
    {
        ostream << "    ----\n";
        ostream << "    Key:\n";
        ostream << "    ----\n";
        if ( entry->usedMacros().empty() )
            ostream << "    Empty key\n";
        else
        {
            for ( Macro const & macro : entry->usedMacros() )
            {
                ostream << "    " << macroName( macro ).str() << macroValue( macro ).str() << '\n';
            }
        }
        ostream << "    --------\n";
        ostream << "    Headers:\n";
        ostream << "    --------\n";
        if ( entry->headers().empty() )
            ostream << "    No headers\n";
        else
        {
            for ( Header const & header : entry->headers() )
            {
                ostream << "    " << header.dir.get().str().str() << ' ' << header.name.get().str().str() << '\n';
            }
        }
        ostream << "    --------\n";
        ostream << "    Content:\n";
        ostream << "    --------\n";
        if ( entry->headers().empty() )
            ostream << "    No content\n";
        else
        {
            std::for_each(
                entry->headerContent().begin(),
                entry->headerContent().end(),
                [&]( HeaderEntry const & he )
                {
                    switch ( he.first )
                    {
                    case MacroUsage::defined:
                        ostream << "    #define " << macroName( he.second ).str() << macroValue( he.second ).str() << '\n';
                        break;
                    case MacroUsage::undefined:
                        ostream << "    #undef " << macroName( he.second ).str() << '\n';
                        break;
                    }
                }
            );
        }
    }

    void dump( std::ostream & ostream )
    {
        for ( CacheContainer::value_type const & entry : cacheContainer_ )
        {
            dumpEntry( entry, ostream );
        }
    }

private:
    void cleanup();

    std::string uniqueFileName();

private:
    struct GetId
    {
        typedef CacheEntry * result_type;
        result_type operator()( CacheEntryPtr const & c ) const
        {
            return &*c;
        }
    };

    struct GetFileId
    {
        typedef FileId result_type;
        result_type operator()( CacheEntryPtr const & c ) const
        {
            return c->fileId();
        }
    };

    struct LastTimeHit
    {
        typedef std::size_t result_type;
        result_type operator()( CacheEntryPtr const & c ) const
        {
            return c->lastTimeHit();
        }
    };

    struct SearchPathId
    {
        typedef std::size_t result_type;
        result_type operator()( CacheEntryPtr const & c ) const
        {
            return c->searchPathId();
        }
    };

    struct ById {};
    struct ByLastTimeHit {};
    struct ByFileIdAndLastTimeHit {};

    typedef boost::multi_index_container<
        CacheEntryPtr,
        boost::multi_index::indexed_by<
            // Index used when searching cache.
            // Entries with recent hits are searched first.
            boost::multi_index::ordered_non_unique<
                boost::multi_index::tag<ByFileIdAndLastTimeHit>,
                boost::multi_index::composite_key<
                    CacheEntryPtr,
                    GetFileId,
                    SearchPathId,
                    LastTimeHit
                >,
                boost::multi_index::composite_key_compare<
                    std::less<FileId>,
                    std::less<std::size_t>,
                    std::greater<std::size_t>
                >
            >,
            // Index used when deleting from cache.
            // Entries with least hits will be removed.
            // Older entries are removed first, to prevent deleting recent
            // additions to cache.
            boost::multi_index::ordered_non_unique<
                boost::multi_index::tag<ByLastTimeHit>,
                LastTimeHit
            >,
            // Unique index is here so that we can update a specific element,
            // without having to hold the lock on the container the entire
            // time.
            boost::multi_index::hashed_unique<
                boost::multi_index::tag<ById>,
                GetId
            >
        >
    > CacheContainer;

    typedef std::unordered_map<std::string, unsigned> FileIds;

private:
    CacheContainer cacheContainer_;
    boost::shared_mutex cacheMutex_;
    unsigned fileIdCounter_;
    std::atomic<std::size_t> counter_;
    std::size_t hits_;
    std::size_t misses_;
};


//------------------------------------------------------------------------------
#endif