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

extern MacroValue undefinedMacroValue;

struct MacroUsage { enum Enum { defined, undefined }; };
class CacheEntry;
typedef boost::intrusive_ptr<CacheEntry> CacheEntryPtr;

struct HeaderWithFileEntry
{
    Header header;
    clang::FileEntry const * file;
};

typedef std::pair<MacroName, MacroValue> Macro;
typedef std::vector<Macro> UsedMacros;

struct GetName
{
    typedef MacroName result_type;
    result_type operator()( Macro const & m ) const
    {
        return m.first;
    }
};

struct ByName {};
struct IndexedUsedMacros : private boost::multi_index_container<
    Macro,
    boost::multi_index::indexed_by<
        boost::multi_index::sequenced<>,
        boost::multi_index::hashed_unique<
            boost::multi_index::tag<ByName>,
            GetName,
            std::hash<MacroName>
        >
    >
>
{
    template <typename MacroValueGetter>
    void addMacro( MacroName const macroName, MacroValueGetter const getter )
    {
        typedef IndexedUsedMacros::index<ByName>::type IndexByMacroName;
        IndexByMacroName & usedMacrosByName( get<ByName>() );
        IndexByMacroName::const_iterator const iter = usedMacrosByName.find( macroName );
        if ( iter != usedMacrosByName.end() )
            return;
        push_back( std::make_pair( macroName, getter( macroName ) ) );
    }

    void addMacro( MacroName const & macroName, MacroValue const & macroValue )
    {
        return addMacro( macroName, [&]( MacroName const & ) -> MacroValue { return macroValue; } );
    }

    template <typename Predicate>
    void forEachUsedMacro( Predicate pred ) const
    {
        std::for_each( begin(), end(), pred );
    }
};

typedef std::unordered_map<MacroName, MacroValue> MacroStateBase;
struct MacroState : public MacroStateBase
{
private:
    MacroState( MacroState const & ms );
    MacroState & operator=( MacroState const & ms );

public:
    MacroState() {}
    MacroState( MacroState && ms ) :
        MacroStateBase( std::move( ms ) ) {}

    void defineMacro( MacroName const & name, MacroValue const & value )
    {
        std::pair<iterator, bool> const insertResult(
            insert( std::make_pair( name, value ) ) );
        if ( !insertResult.second )
            insertResult.first->second = value;
    }

    void undefineMacro( MacroName const & name )
    {
        defineMacro( name, undefinedMacroValue );
    }

    bool getMacroValue( MacroName const & name, MacroValue & value ) const
    {
        const_iterator const result = find( name );
        if ( result == end() )
            return false;
        value = result->second;
        return true;
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
        UsedMacros && usedMacros,
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

    template <typename Predicate>
    void forEachUsedMacro( Predicate pred ) const
    {
        std::for_each( usedMacros_.begin(), usedMacros_.end(), pred );
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
    UsedMacros usedMacros_;
    MacroState macroState_;
    Headers headers_;
    std::size_t lastTimeHit_;
    std::atomic_flag contentLock_;
    std::string buffer_;
    llvm::OwningPtr<llvm::MemoryBuffer> memoryBuffer_;
    bool detached_;
};


inline void intrusive_ptr_add_ref( CacheEntry * c ) { c->addRef(); }
inline void intrusive_ptr_release( CacheEntry * c ) { c->decRef(); }

class CacheTree
{
public:
    CacheTree() : entry_( 0 ), parent_( 0 ) {}

    CacheTree & getChild( UsedMacros const & usedMacros )
    {
        CacheTree * currentTree = this;
        for ( UsedMacros::value_type const & macro : usedMacros )
            currentTree = &currentTree->getChild( macro.first, macro.second );
        assert( currentTree->getPath() == usedMacros );
        assert( currentTree->children_.empty() );
        return *currentTree;
    }

    CacheEntryPtr find( HeaderCtx const & headerCtx ) const;

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
    void setParent( CacheTree & parent, MacroValue const macroValue )
    {
        parent_ = &parent;
        macroValue_ = macroValue;
    }

    CacheTree & getChild( MacroName const & name, MacroValue const & value )
    {
        if ( !macroName_ )
            macroName_ = name;
#ifndef NDEBUG
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
        UsedMacros && usedMacros,
        MacroState && macroState,
        Headers && headers
    );

    CacheEntryPtr findEntry
    (
        FileId const & id,
        std::size_t searchPathId,
        HeaderCtx const &
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