//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef headerCache_HPP__A615CA5B_F047_45DE_8314_AF96E4F4FF86
#define headerCache_HPP__A615CA5B_F047_45DE_8314_AF96E4F4FF86
//------------------------------------------------------------------------------
#include "contentCache_.hpp"
#include "headerScanner_.hpp"
#include "macroState_.hpp"
#include "utility_.hpp"

#include <boost/intrusive_ptr.hpp>
#include <boost/container/list.hpp>
#include <boost/multi_index_container.hpp>
#include <boost/multi_index/composite_key.hpp>
#include <boost/multi_index/hashed_index.hpp>
#include <boost/multi_index/member.hpp>
#include <boost/multi_index/ordered_index.hpp>
#include <boost/multi_index/sequenced_index.hpp>
#include <boost/thread/lock_algorithms.hpp>
#include <boost/thread/shared_mutex.hpp>
#include <boost/thread/mutex.hpp>
  
#include <llvm/Support/MemoryBuffer.h>
#include <llvm/Support/raw_ostream.h>

#include <atomic>
#include <list>
#include <map>
#include <set>
#include <string>
#include <tuple>
#include <vector>
#include <fstream>
#include <windows.h>

class HeaderCtx;

namespace clang
{
    class FileEntry;
}

struct MacroUsage { enum Enum { defined, undefined }; };
class CacheEntry;
typedef boost::intrusive_ptr<CacheEntry> CacheEntryPtr;

struct HeaderWithFileEntry
{
    Header header;
    clang::FileEntry const * file;
};

typedef std::vector<Macro> UsedMacros;

////////////////////////////////////////////////////////////////////////////////
//
// IndexedUsedMacros
// -----------------
//
//   A list of macros without duplicates. Uses double indexing to implement
// constant time insert operation.
//
////////////////////////////////////////////////////////////////////////////////

typedef boost::multi_index_container<
    Macro,
    boost::multi_index::indexed_by<
        boost::multi_index::sequenced<>,
        boost::multi_index::hashed_unique<
            boost::multi_index::member<Macro, MacroName, &Macro::first>,
            std::hash<MacroName>
        >
    >
> IndexedUsedMacrosBase;

struct IndexedUsedMacros : public IndexedUsedMacrosBase
{
    template <typename MacroValueGetter>
    bool addMacro( MacroName const & macroName, MacroValueGetter const getter )
    {
        typedef IndexedUsedMacrosBase::nth_index<1>::type IndexByMacroName;
        IndexByMacroName & usedMacrosByName( get<1>() );
        IndexByMacroName::const_iterator const iter = usedMacrosByName.find( macroName );
        if ( iter != usedMacrosByName.end() )
            return false;
        push_back( std::make_pair( macroName, getter( macroName ) ) );
        return true;
    }

    bool addMacro( MacroName const & macroName, MacroValue const & macroValue )
    {
        return addMacro( macroName, [&]( MacroName const & ) -> MacroValue { return macroValue; } );
    }
};

void intrusive_ptr_add_ref( CacheEntry * );
void intrusive_ptr_release( CacheEntry * );

typedef llvm::sys::fs::UniqueID FileId;

class Cache;
class CacheTree;

class CacheEntry
{
public:
    CacheEntry
    (
        CacheTree & tree,
        std::string const & uniqueVirtualFileName,
        MacroState && macroState,
        Headers && headers,
        std::size_t currentTime
    );

    clang::FileEntry const * getFileEntry( clang::SourceManager & );
    llvm::MemoryBuffer const * cachedContent();

    ~CacheEntry();

    bool usesBuffer( llvm::MemoryBuffer const * buffer ) const
    {
        return std::find_if(
            headers_.begin(),
            headers_.end(),
            [=]( Header const & header )
            {
                return header.contentEntry->buffer.get() == buffer;
            }
        ) != headers_.end();
    }

    template <typename F>
    void forEachUsedMacro( F & f ) const
    {
        UsedMacros usedMacros( tree_.getPath() );
        std::for_each( usedMacros.begin(), usedMacros.end(), f );
    }

    Headers    const & headers   () const { return headers_; }
    MacroState const & macroState() const { return macroState_; }

    std::size_t lastTimeHit() const { return lastTimeHit_; }

    void setLastTimeHit( unsigned int lastTimeHit )
    {
        lastTimeHit_ = lastTimeHit;
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

    CacheTree & tree_;
    std::string fileName_;
    MacroState macroState_;
    Headers headers_;
    std::size_t lastTimeHit_;
    std::atomic_flag contentLock_;
    std::string buffer_;
    llvm::OwningPtr<llvm::MemoryBuffer> memoryBuffer_;
};


inline void intrusive_ptr_add_ref( CacheEntry * c ) { c->addRef(); }
inline void intrusive_ptr_release( CacheEntry * c ) { c->decRef(); }

class CacheTree
{
public:
    CacheTree() : entry_( 0 ), parent_( 0 ) {}

    template <typename MacroList>
    CacheTree & getChild( MacroList const & usedMacros )
    {
        CacheTree * currentTree = this;
        for ( Macro const & macro : usedMacros )
            currentTree = &currentTree->getChild( macro.first, macro.second );
#ifndef NDEBUG
        UsedMacros path = currentTree->getPath();
        assert( std::equal( usedMacros.begin(), usedMacros.end(), path.begin() ) );
#endif
        assert( currentTree->children_.empty() );
        return *currentTree;
    }

    CacheEntryPtr find( MacroState const & ) const;

    void detach()
    {
        setEntry( 0 );
        CacheTree * parent( 0 );
        std::swap( parent_, parent );
        assert( !parent->children_.empty() );
        parent->children_.erase( macroValue_ );

        while ( parent->children_.empty() )
        {
            CacheTree * gp = parent->parent_;
            if ( !gp )
                return;
            gp->children_.erase( parent->macroValue_ );
            parent = gp;
        }
    }

    void setEntry( CacheEntry * entry )
    {
        assert( !entry || children_.empty() );
        entry_ = entry;
    }

    CacheEntry * getEntry() const
    {
        return entry_;
    }

    UsedMacros getPath() const
    {
        UsedMacros result;
        CacheTree const * current = this;
        while ( current->parent_ )
        {
            result.push_back( std::make_pair( current->parent_->macroName_, current->macroValue_ ) );
            current = current->parent_;
        }
        std::reverse( result.begin(), result.end() );
        return result;
    }

private:
    typedef std::unordered_map<MacroValue, CacheTree> Children;
    void setParent( CacheTree & parent, MacroValue const & macroValue )
    {
        parent_ = &parent;
        macroValue_ = macroValue;
    }

    CacheTree & getChild( MacroName const & name, MacroValue const & value )
    {
        if ( !macroName_ )
            macroName_ = name;
#ifdef DEBUG_HEADERS
        if ( macroName_ != name )
        {
            {
                std::ofstream stream( "tree_conflict.txt" );
                stream << "Conflict - expected '" << macroName_.get().str().str() << "' got '" << name.get().str().str() << "'\n";
                CacheTree * current = parent_;
                MacroValue val = macroValue_;
                while ( current )
                {
                    stream << current->macroName_.get().str().str() << ' ' << val.get().str().str() << '\n';
                    if ( current->parent_ )
                        val = current->macroValue_;
                    current = current->parent_;
                }
            }
            DebugBreak();
        }
#endif
        assert( !getEntry() );
        std::pair<Children::iterator, bool> insertResult = children_.insert( std::make_pair( value, CacheTree() ) );
        CacheTree & result = insertResult.first->second;
        if ( insertResult.second )
            result.setParent( *this, value );
        return result;
    }

private:
    MacroName macroName_;
    CacheEntry * entry_;

    Children children_;

    CacheTree * parent_;
    MacroValue macroValue_;
};

inline CacheEntry::~CacheEntry()
{
    tree_.detach();
}


class Cache
{
public:
    Cache() : counter_( 0 ), hits_( 0 ), misses_( 0 ) {}
    ~Cache()
    {
        // Clearing all cache entries will cause cache tree index
        // to be destroyed bottom-up, and will avoid (potentially)
        // very long recursive call chain.
        cacheEntries_.clear();
    }

    CacheEntryPtr addEntry
    (
        FileId const & id,
        std::size_t searchPathId,
        IndexedUsedMacros const & usedMacros,
        MacroState && macroState,
        Headers && headers
    );

    CacheEntryPtr findEntry
    (
        FileId const & id,
        std::size_t searchPathId,
        MacroState const &
    );

    void invalidate( ContentEntry const & );

    std::size_t hits() const { return hits_; }
    std::size_t misses() const { return misses_; }

private:
    friend class CacheEntry;

private:
    void maintenance();
    std::string uniqueFileName();

private:
    typedef std::map<std::pair<FileId, std::size_t>, CacheTree> CacheContainer;

    struct GetId
    {
        typedef CacheEntry * result_type;
        result_type operator()( CacheEntryPtr const & c ) const
        {
            return &*c;
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

    struct ById {};
    struct ByLastTimeHit {};

    typedef boost::multi_index_container<
        CacheEntryPtr,
        boost::multi_index::indexed_by<
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
    > CacheEntries;


private:
    CacheContainer cacheContainer_;
    CacheEntries cacheEntries_;
    boost::shared_mutex cacheMutex_;
    boost::mutex tempLastTimeHitMutex_;
    std::map<CacheEntryPtr, unsigned int> tempLastTimeHit_;
    std::atomic<std::size_t> counter_;
    std::size_t hits_;
    std::size_t misses_;
};


//------------------------------------------------------------------------------
#endif
