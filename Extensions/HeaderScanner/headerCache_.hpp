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
#include <map>
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

typedef std::vector<std::pair<MacroName, MacroValue> > UsedMacros;

template <typename MacroValueGetter>
void addUsedMacro( UsedMacros & macros, MacroName const macroName, MacroValueGetter const getter )
{
    if ( std::find_if( macros.begin(), macros.end(),
        [&]( UsedMacros::value_type const & oldMacro )
        {
            return oldMacro.first == macroName;
        }) != macros.end() )
        return;
    macros.push_back( std::make_pair( macroName, getter( macroName ) ) );
}

inline void addUsedMacro( UsedMacros & macros, MacroName const macroName, MacroValue const macroValue )
{
    if ( std::find_if( macros.begin(), macros.end(),
        [&]( UsedMacros::value_type const & oldMacro )
        {
            return oldMacro.first == macroName;
        }) != macros.end() )
        return;
    macros.push_back( std::make_pair( macroName, macroValue ) );
}

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

class CacheTree;

class CacheEntry
{
private:
    CacheEntry
    (
        CacheTree & tree,
        std::string const & uniqueVirtualFileName,
        MacroState && definedMacros,
        MacroNames && undefinedMacros,
        Headers && headers,
        std::size_t currentTime
    );

public:
    static CacheEntryPtr create
    (
        CacheTree & tree,
        std::string const & uniqueVirtualFileName,
        MacroState && definedMacros,
        MacroNames && undefinedMacros,
        Headers && headers,
        std::size_t currentTime
    );
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

    UsedMacros         usedMacros     () const;
    Headers    const & headers        () const { return headers_; }
    MacroNames const & undefinedMacros() const { return undefinedMacros_; }
    MacroState const & definedMacros  () const { return definedMacros_; }

    void detach();
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
    CacheTree & tree_;
    std::string fileName_;
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

class CacheTree
{
public:
    typedef std::map<MacroValue, CacheTree> Children;

public:
    CacheTree() : parent_( 0 ) {}

    CacheTree & getChild( UsedMacros const & usedMacros )
    {
        CacheTree * currentTree = this;
        for ( UsedMacros::value_type const & macro : usedMacros )
            currentTree = &currentTree->getChild( macro.first, macro.second );
        assert( currentTree->getPath() == usedMacros );
        return *currentTree;
    }

    CacheEntryPtr find( HeaderCtx const & headerCtx ) const;

    void detach()
    {
        if ( !parent_ )
            return;

        CacheTree * const parent( parent_ );
        parent_ = 0;
        parent->children_.erase( pos_ );
        if ( parent->children_.size() == 0 )
            parent->detach();
    }

    void setEntry( CacheEntryPtr entry )
    {
        entry_ = entry;
    }

    CacheEntryPtr getEntry() const
    {
        return entry_;
    }

    UsedMacros getPath() const
    {
        UsedMacros result;
        CacheTree const * current = this;
        while ( current->parent_ )
        {
            result.push_back( std::make_pair( current->parent_->macroName_, current->pos_->first ) );
            current = current->parent_;
        }
        std::reverse( result.begin(), result.end() );
        return result;
    }

private:
    void setParent( CacheTree & parent, Children::iterator const pos )
    {
        parent_ = &parent;
        pos_ = pos;
    }

    CacheTree & getChild( MacroName name, MacroValue value )
    {
        if ( !macroName_ )
            macroName_ = name;
        assert( macroName_ == name );

        std::pair<Children::iterator, bool> insertResult = children_.insert( std::make_pair( value, CacheTree() ) );
        CacheTree & result = insertResult.first->second;
        if ( insertResult.second )
            result.setParent( *this, insertResult.first );
        return result;
    }

private:
    MacroName macroName_;
    CacheEntryPtr entry_;

    Children children_;

    CacheTree * parent_;
    Children::iterator pos_;
};

inline UsedMacros CacheEntry::usedMacros() const
{
    return tree_.getPath();
}

inline void CacheEntry::detach()
{
    tree_.detach();
}


class Cache
{
public:
    Cache() : counter_( 0 ), hits_( 0 ), misses_( 0 ) {}

    CacheEntryPtr addEntry
    (
        FileId const & id,
        std::size_t searchPathId,
        UsedMacros && usedMacros,
        MacroState && definedMacros,
        MacroNames && undefinedMacros,
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
    std::atomic<std::size_t> counter_;
    std::size_t hits_;
    std::size_t misses_;
};


//------------------------------------------------------------------------------
#endif