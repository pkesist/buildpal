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
  
#include <llvm/Support/MemoryBuffer.h>
#include <llvm/Support/raw_ostream.h>

#include <atomic>
#include <list>
#include <set>
#include <string>
#include <tuple>
#include <vector>

struct HeaderCtx;

namespace clang
{
    class FileEntry;
}

extern MacroValue undefinedMacroValue;

struct MacroUsage { enum Enum { defined, undefined }; };
class CacheEntry;
typedef boost::intrusive_ptr<CacheEntry> CacheEntryPtr;

typedef std::set<MacroName> MacroNamesBase;
struct MacroNames : public MacroNamesBase
{
public:
    MacroNames() {}

    MacroNames( MacroNames && mn ) :
        MacroNamesBase( std::move( mn ) ) {}

private:
    MacroNames( MacroNames const & );
    MacroNames & operator=( MacroNames const & );
};

struct HeaderWithFileEntry
{
    Header header;
    clang::FileEntry const * file;
};

typedef std::map<MacroName, MacroValue> MacroStateBase;
struct MacroState : public MacroStateBase
{
private:
    MacroState( MacroState const & ms );
    MacroState & operator=( MacroState const & ms );

public:
    MacroState() {}
    MacroState( MacroState && ms ) :
        MacroStateBase( std::move( ms ) ) {}

    MacroValue macroValue( MacroName macroName ) const
    {
        MacroState::const_iterator const iter( find( macroName ) );
        return iter == end() ? undefinedMacroValue : iter->second;
    }

    void defineMacro( MacroName name, MacroValue value )
    {
        std::pair<iterator, bool> const insertResult(
            insert( std::make_pair( name, value ) ) );
        if ( !insertResult.second )
            insertResult.first->second = value;
    }

    void undefineMacro( MacroName name )
    {
        erase( name );
    }

    void merge( MacroState const & other )
    {
        iterator firstIter = begin();
        iterator const firstEnd = end();
        const_iterator secondIter = other.begin();
        const_iterator const secondEnd = other.end();
        while ( ( firstIter != firstEnd ) && ( secondIter != secondEnd ) )
        {
            if ( firstIter->first < secondIter->first )
            {
                firstIter = lower_bound( secondIter->first );
            }
            else if ( firstIter->first > secondIter->first )
            {
                const_iterator const tmpEnd = other.upper_bound( firstIter->first );
                iterator insertHint = firstIter;
                for ( ; secondIter != tmpEnd; ++secondIter )
                {
                    insertHint = insert( insertHint, *secondIter );
                    ++insertHint;
                }
            }
            else
            {
                firstIter->second = secondIter->second;
                ++firstIter;
                ++secondIter;
            }
        }
        insert( secondIter, secondEnd );
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
        MacroState && usedMacros,
        MacroState && definedMacros,
        MacroNames && undefinedMacros,
        Headers && headers,
        std::size_t currentTime

    ) :
        refCount_( 0 ),
        searchPathId_( searchPathId ),
        fileId_( fileId ),
        fileName_( uniqueVirtualFileName ),
        usedMacros_( std::move( usedMacros ) ),
        definedMacros_( std::move( definedMacros ) ),
        undefinedMacros_( std::move( undefinedMacros ) ),
        headers_( std::move( headers ) ),
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
        MacroState && usedMacros,
        MacroState && definedMacros,
        MacroNames && undefinedMacros,
        Headers && headers,
        unsigned currentTime
    )
    {
        CacheEntry * result = new CacheEntry
        (
            fileId,
            searchPathId,
            uniqueVirtualFileName,
            std::move( usedMacros ),
            std::move( definedMacros ),
            std::move( undefinedMacros ),
            std::move( headers ),
            currentTime
        );
        return CacheEntryPtr( result );
    }

    clang::FileEntry const * getFileEntry( clang::SourceManager & );
    llvm::MemoryBuffer const * cachedContent();

    bool usesBuffer( llvm::MemoryBuffer const * buffer ) const
    {
        return std::find_if(
            headers_.begin(),
            headers_.end(),
            [=]( Header const & header )
            {
                return header.buffer == buffer;
            }
        ) != headers_.end();
    }

    MacroState const & usedMacros     () const { return usedMacros_; }
    Headers    const & headers        () const { return headers_; }
    MacroNames const & undefinedMacros() const { return undefinedMacros_; }
    MacroState const & definedMacros  () const { return definedMacros_; }

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
    MacroState usedMacros_;
    MacroNames undefinedMacros_;
    MacroState definedMacros_;
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
    Cache() : counter_( 0 ), hits_( 0 ), misses_( 0 ) {}

    CacheEntryPtr addEntry
    (
        llvm::sys::fs::UniqueID const & id,
        std::size_t searchPathId,
        MacroState && usedMacros,
        MacroState && definedMacros,
        MacroNames && undefinedMacros,
        Headers && headers
    );

    CacheEntryPtr findEntry
    (
        llvm::sys::fs::UniqueID const & id,
        std::size_t searchPathId,
        HeaderCtx const &
    );

    void invalidate( ContentEntry const & );

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
            for ( MacroState::value_type const & macro : entry->usedMacros() )
            {
                ostream << "    " << macro.first << macro.second << '\n';
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
        if ( entry->undefinedMacros().empty() && entry->definedMacros().empty() )
            ostream << "    No content\n";
        else
        {
            std::for_each(
                entry->undefinedMacros().begin(),
                entry->undefinedMacros().end  (),
                [&]( MacroName macroName )
                {
                    ostream << "#undef " << macroName << '\n';
                }
            );
            std::for_each(
                entry->definedMacros().begin(),
                entry->definedMacros().end  (),
                [&]( MacroState::value_type const & macro )
                {
                    ostream << "#define " << macro.first << macro.second << '\n';
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
    void maintenance();

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

private:
    CacheContainer cacheContainer_;
    boost::shared_mutex cacheMutex_;
    std::atomic<std::size_t> counter_;
    std::size_t hits_;
    std::size_t misses_;
};


//------------------------------------------------------------------------------
#endif