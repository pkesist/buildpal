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
#include <boost/flyweight/no_locking.hpp>
#include <boost/flyweight/no_tracking.hpp>
#include <boost/flyweight/static_holder.hpp>
#include <boost/flyweight/refcounted.hpp>
#include <boost/multi_index_container.hpp>
#include <boost/multi_index/ordered_index.hpp>
#include <boost/multi_index/sequenced_index.hpp>
#include <boost/functional/hash.hpp>
#include <boost/thread/locks.hpp>
#include <boost/thread/lock_types.hpp> 

#include <llvm/ADT/StringMap.h>
#include <llvm/Support/MemoryBuffer.h>

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

struct HashStrRef
{
    std::size_t operator()( llvm::StringRef str )
    {
        return boost::hash_range( str.data(), str.data() + str.size() );
    }
};

typedef std::pair<llvm::StringRef, llvm::StringRef> MacroRef;
typedef std::unordered_map<llvm::StringRef, llvm::StringRef, HashStrRef> MacroRefs;

#define DEFINE_FLYWEIGHT(base, name) \
    struct name##Tag {}; \
    typedef boost::flyweight<base, \
        boost::flyweights::tag<name##Tag>, \
        boost::flyweights::no_locking, \
        boost::flyweights::no_tracking> name

DEFINE_FLYWEIGHT(std::string, Dir);
DEFINE_FLYWEIGHT(std::string, HeaderName);
DEFINE_FLYWEIGHT(std::string, MacroName);
typedef std::string MacroValue;
//DEFINE_FLYWEIGHT(std::string, MacroValue);

typedef std::tuple<Dir, HeaderName, clang::FileEntry const *, HeaderLocation::Enum> HeaderFile;

typedef boost::container::flat_map<MacroName, MacroValue> Macros;
typedef Macros::value_type Macro;

template<typename T>
inline T fromDataAndSize( char const * data, std::size_t size )
{
    return T( data, size );
}

inline Macro macroFromMacroRef( MacroRef const & macroRef )
{
    return std::make_pair(
        MacroName( macroRef.first.data(), macroRef.first.size() ),
        MacroValue( macroRef.second.data(), macroRef.second.size() ) );
}

inline llvm::StringRef macroName( Macro const & macro )
{
    return macro.first.get();
}

inline llvm::StringRef macroValue( Macro const & macro )
{
    return macro.second;
}

inline MacroRef macroRefFromMacro( Macro const & macro )
{
    return std::make_pair( macroName( macro ), macroValue( macro ) );
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
        MacroRefs const & usedMacros,
        HeaderContent const & headerContent,
        Headers const & headers
    ) :
        uid_( uid ),
        fileName_( uniqueVirtualFileName ),
        headerContent_( headerContent ),
        headers_( headers ),
        refCount_( 0 )
    {
        std::transform( usedMacros.begin(), usedMacros.end(),
            std::inserter( usedMacros_, usedMacros_.begin() ),
            []( MacroRef macroRef ) { return macroFromMacroRef( macroRef ); } );
    }

public:
    static CacheEntryPtr create
    (
        unsigned uid,
        std::string const & uniqueVirtualFileName,
        MacroRefs const & usedMacros,
        HeaderContent const & headerContent,
        Headers const & headers
    )
    {
        CacheEntry * result = new CacheEntry
        (
            uid,
            uniqueVirtualFileName,
            usedMacros,
            headerContent,
            headers
        );
        return CacheEntryPtr( result );
    }

    clang::FileEntry const * getFileEntry( clang::SourceManager & );
    void releaseFileEntry( clang::SourceManager & );
    void generateContent();

    Macros        const & usedMacros   () const { return usedMacros_; }
    HeaderContent       & headerContent()       { return headerContent_; }
    HeaderContent const & headerContent() const { return headerContent_; }
    Headers       const & headers      () const { return headers_; }
    unsigned uid() const { return uid_; }

private:
    friend void intrusive_ptr_add_ref( CacheEntry * );
    friend void intrusive_ptr_release( CacheEntry * );

    void addRef() { ++refCount_; }
    void decRef()
    {
        refCount_--;
        if ( refCount_ == 0 )
            delete this;
    }

private:
    unsigned uid_;
    std::string fileName_;
    Macros usedMacros_;
    HeaderContent headerContent_;
    Headers headers_;
    std::size_t refCount_;
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
        clang::FileEntry const * file,
        MacroRefs const & macros,
        HeaderContent const & headerContent,
        Headers const & headers
    )
    {
        CacheEntryPtr result = CacheEntry::create( file->getUID(), uniqueFileName(),
            macros, headerContent, headers );
        cacheContainer_.push_back( result );
        return result;
    }

    CacheEntryPtr findEntry
    (
        unsigned uid,
        MacroState const & macroState
    );

    std::size_t hits() const { return hits_; }
    std::size_t misses() const { return misses_; }

private:
    std::string uniqueFileName();

private:
    struct ByUid {};

    struct GetUid
    {
        typedef unsigned result_type;
        result_type operator()( CacheEntryPtr const & c ) const
        {
            return c->uid();
        }
    };

    typedef boost::multi_index_container<
        CacheEntryPtr,
        boost::multi_index::indexed_by<
            boost::multi_index::sequenced<>,
            boost::multi_index::ordered_non_unique<
                boost::multi_index::tag<ByUid>, GetUid>
        >
    > CacheContainer;

private:
    CacheContainer cacheContainer_;
    std::size_t counter_;
    std::size_t hits_;
    std::size_t misses_;
};


//------------------------------------------------------------------------------
#endif