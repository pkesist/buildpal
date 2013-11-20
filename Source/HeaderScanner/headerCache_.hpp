//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef headerCache_HPP__A615CA5B_F047_45DE_8314_AF96E4F4FF86
#define headerCache_HPP__A615CA5B_F047_45DE_8314_AF96E4F4FF86
//------------------------------------------------------------------------------
#include "headerScanner_.hpp"

#include <boost/intrusive_ptr.hpp>
#include <boost/variant.hpp>
#include <boost/container/list.hpp>
#include <boost/container/flat_map.hpp>
#include <boost/flyweight/flyweight.hpp>
#include <boost/flyweight/hashed_factory.hpp>
#include <boost/flyweight/tag.hpp>
#include <boost/flyweight/simple_locking.hpp>
#include <boost/flyweight/no_tracking.hpp>
#include <boost/flyweight/static_holder.hpp>
#include <boost/flyweight/refcounted.hpp>
#include <boost/multi_index_container.hpp>
#include <boost/multi_index/composite_key.hpp>
#include <boost/multi_index/ordered_index.hpp>
#include <boost/functional/hash.hpp>

#include <llvm/ADT/StringMap.h>
#include <llvm/Support/MemoryBuffer.h>

#include <atomic>
#include <mutex>
#include <list>
#include <set>
#include <string>
#include <tuple>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace clang
{
    class FileEntry;
}

#define DEFINE_FLYWEIGHT(base, name) \
    struct name##Tag {}; \
    typedef boost::flyweight<base, \
        boost::flyweights::tag<name##Tag>, \
        boost::flyweights::no_tracking> name

DEFINE_FLYWEIGHT(std::string, Dir);
DEFINE_FLYWEIGHT(std::string, HeaderName);
DEFINE_FLYWEIGHT(std::string, MacroName);
DEFINE_FLYWEIGHT(std::string, MacroValue);

typedef std::tuple<Dir, HeaderName, clang::FileEntry const *, HeaderLocation::Enum> HeaderFile;

typedef boost::container::flat_map<MacroName, MacroValue> Macros;
typedef Macros::value_type Macro;

inline Macro createMacro( llvm::StringRef name, llvm::StringRef value )
{
    return std::make_pair( MacroName( name ), MacroValue( value ) );
}

template<typename T>
inline T fromDataAndSize( char const * data, std::size_t size )
{
    return T( data, size );
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
typedef std::pair<MacroUsage::Enum, Macro> MacroWithUsage;
class CacheEntry;
typedef boost::intrusive_ptr<CacheEntry> CacheEntryPtr;
typedef boost::variant<HeaderFile, CacheEntryPtr> Header;
typedef std::vector<Header> Headers;
typedef boost::variant<MacroWithUsage, CacheEntryPtr> HeaderEntry;
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
        llvm::StringMapEntry<llvm::StringRef> * const entry(
            llvm::StringMapEntry<llvm::StringRef>::Create(
                name.data(), name.data() + name.size(),
                getAllocator(), value ) );
        bool const insertSuccess = insert( entry );
        // It is OK to #define macro to its current value.
        // If this assertion fires, you most likely messed up the header cache.
        // UPDATE: Unfortunately, some libraries (e.g. OpenSSL) #define macros to
        // the sytactically same value, but lexically different.
        //assert( insertSuccess || macroState()[ name ] == macroDef );
    }

    void undefineMacro( llvm::StringRef name )
    {
        erase( name );
    }
};

void intrusive_ptr_add_ref( CacheEntry * );
void intrusive_ptr_release( CacheEntry * );

class CacheEntry
{
private:
    CacheEntry
    (
        unsigned uid,
        std::string const & uniqueVirtualFileName,
        Macros const & usedMacros,
        HeaderContent const & headerContent,
        Headers const & headers,
        unsigned includeDepth

    ) :
        refCount_( 0 ),
        uid_( uid ),
        usedMacros_( usedMacros ),
        fileName_( uniqueVirtualFileName ),
        headerContent_( headerContent ),
        headers_( headers ),
        hitCount_( 0 ),
        includeDepth_( 0 )
    {
    }

public:
    static CacheEntryPtr create
    (
        unsigned uid,
        std::string const & uniqueVirtualFileName,
        Macros const & usedMacros,
        HeaderContent const & headerContent,
        Headers const & headers,
        unsigned includeDepth
    )
    {
        CacheEntry * result = new CacheEntry
        (
            uid,
            uniqueVirtualFileName,
            usedMacros,
            headerContent,
            headers,
            includeDepth
        );
        return CacheEntryPtr( result );
    }

    clang::FileEntry const * getFileEntry( clang::SourceManager & );
    void generateContent( std::recursive_mutex & );

    unsigned             includeDepth  () const { return includeDepth_; }
    Macros        const & usedMacros   () const { return usedMacros_; }
    HeaderContent       & headerContent()       { return headerContent_; }
    HeaderContent const & headerContent() const { return headerContent_; }
    Headers       const & headers      () const { return headers_; }
    unsigned uid() const { return uid_; }
    std::size_t hitCount() const { return hitCount_; }
    
    void incHitCount() { ++hitCount_; }

private:
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
    unsigned uid_;
    std::string fileName_;
    Macros usedMacros_;
    HeaderContent headerContent_;
    Headers headers_;
    std::size_t hitCount_;
    unsigned includeDepth_;
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
        llvm::StringRef fileName,
        Macros const & macros,
        HeaderContent const & headerContent,
        Headers const & headers,
        unsigned includeDepth
    )
    {
        unsigned const uid( getFileId( fileName ) );
        CacheEntryPtr result = CacheEntry::create( uid, uniqueFileName(),
            macros, headerContent, headers, includeDepth );
        std::unique_lock<std::mutex> const lock( cacheMutex_ );
        cacheContainer_.insert( result );
        return result;
    }

    CacheEntryPtr findEntry
    (
        llvm::StringRef fileName,
        MacroState const & macroState
    );

    unsigned getFileId( llvm::StringRef name )
    {
        std::unique_lock<std::mutex> const fileIdsLock( fileIdsMutex_ );
        FileIds::const_iterator const iter( fileIds_.find( name ) );
        if ( iter != fileIds_.end() )
            return iter->second;
        fileIds_[ name ] = ++fileIdCounter_;
        return fileIdCounter_;
    }

    std::size_t hits() const { return hits_; }
    std::size_t misses() const { return misses_; }

private:
    std::string uniqueFileName();

private:
    struct GetUid
    {
        typedef unsigned result_type;
        result_type operator()( CacheEntryPtr const & c ) const
        {
            return c->uid();
        }
    };

    struct GetHitCount
    {
        typedef std::size_t result_type;
        result_type operator()( CacheEntryPtr const & c ) const
        {
            return c->hitCount();
        }
    };

    struct ByUidAndHitCount {};

    typedef boost::multi_index_container<
        CacheEntryPtr,
        boost::multi_index::indexed_by<
            boost::multi_index::ordered_non_unique<
                boost::multi_index::tag<ByUidAndHitCount>,
                boost::multi_index::composite_key<
                    CacheEntryPtr,
                    GetUid
                    //GetHitCount
                >,
                boost::multi_index::composite_key_compare<
                    std::less<unsigned>
                    //std::greater<std::size_t>
                >
            >
        >
    > CacheContainer;

    typedef std::unordered_map<std::string, unsigned> FileIds;

private:
    CacheContainer cacheContainer_;
    std::mutex cacheMutex_;
    FileIds fileIds_;
    std::mutex fileIdsMutex_;
    unsigned fileIdCounter_;
    std::recursive_mutex generateContentMutex_;
    std::size_t counter_;
    std::size_t hits_;
    std::size_t misses_;
};


//------------------------------------------------------------------------------
#endif