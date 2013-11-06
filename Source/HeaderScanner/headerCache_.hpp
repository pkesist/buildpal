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
//------------------------------------------------------------------------------
#define POOL_MACROS_USING_BOOST_FLYWEIGHT
#ifdef POOL_MACROS_USING_BOOST_FLYWEIGHT
#include <boost/flyweight/flyweight.hpp>
#include <boost/flyweight/hashed_factory.hpp>
#include <boost/flyweight/tag.hpp>
#include <boost/flyweight/no_locking.hpp>
#include <boost/flyweight/no_tracking.hpp>
#include <boost/flyweight/static_holder.hpp>
#include <boost/flyweight/refcounted.hpp>
#elif defined(POOL_MACROS_USING_LLVM_STRINGPOOL)
#include <llvm/Support/StringPool.h>
#endif
//------------------------------------------------------------------------------

namespace clang
{
    class FileEntry;
}

typedef std::pair<llvm::StringRef, llvm::StringRef> MacroRef;
typedef boost::container::flat_map<llvm::StringRef, llvm::StringRef> MacroRefs;

#ifdef POOL_MACROS_USING_BOOST_FLYWEIGHT
struct HeaderNameTag {};

namespace BF = boost::flyweights;
typedef boost::flyweight<std::string, BF::tag<HeaderNameTag>, BF::no_locking, BF::no_tracking> HeaderName;
typedef std::tuple<HeaderName, clang::FileEntry const *, HeaderLocation::Enum> HeaderFile;
struct MacroNameTag {};
typedef boost::flyweight<std::string, BF::tag<MacroNameTag>, BF::no_locking, BF::no_tracking> MacroName;
struct MacroValueTag {};
typedef boost::flyweight<std::string, BF::tag<MacroValueTag>, BF::no_locking, BF::no_tracking> MacroValue;

typedef boost::container::flat_map<MacroName, MacroValue> Macros;
typedef Macros::value_type Macro;

inline HeaderName headerNameFromDataAndSize( char const * data, std::size_t size )
{
    return HeaderName( data, size );
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
    return macro.second.get();
}

inline MacroRef macroRefFromMacro( Macro const & macro )
{
    return std::make_pair( macroName( macro ), macroValue( macro ) );
}
#else
typedef std::string MacroName;
typedef std::string MacroValue;

typedef boost::container::flat_map<MacroName, MacroValue> Macros;
typedef Macros::value_type Macro;

inline Macro macroFromMacroRef( MacroRef const & macroRef )
{
    return macroRef;
}

inline llvm::StringRef macroName( Macro const & macro )
{
    return macro.first;
}

inline llvm::StringRef macroValue( Macro const & macro )
{
    return macro.second;
}

inline MacroRef macroRefFromMacro( Macro const & macro )
{
    return macro;
}
#endif // DONT_USE_POOLED_MACROS_IN_CACHE

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
        std::string const & uniqueVirtualFileName,
        MacroRefs const & usedMacros,
        HeaderContent const & headerContent,
        Headers const & headers
    ) : 
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
        std::string const & uniqueVirtualFileName,
        MacroRefs const & usedMacros,
        HeaderContent const & headerContent,
        Headers const & headers
    )
    {
        CacheEntry * result = new CacheEntry
        (
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

    typedef CacheEntry CacheEntry;

    class HeaderInfo
    {
    private:
        HeaderInfo( HeaderInfo const & );
        HeaderInfo & operator=( HeaderInfo & );

    public:
        typedef boost::container::list<CacheEntryPtr> CacheList;

        HeaderInfo( std::string const & header, std::size_t const size )
            :
            header_( header )
        {}

        HeaderInfo( HeaderInfo && other )
            :
            cacheList_( other.cacheList_ )
        {
            header_.swap( other.header_ );
        }

        HeaderInfo & operator=( HeaderInfo && other )
        {
            header_.swap( other.header_ );
            cacheList_ = other.cacheList_;
            return *this;
        }

        CacheEntryPtr findCacheEntry( MacroState const & );
        void insert( CacheEntryPtr c ) { cacheList_.push_front( c ); }

        std::string const & header() const { return header_; }

    private:
        std::string header_;
        CacheList cacheList_;
    };

    CacheEntryPtr addEntry
    (
        clang::FileEntry const * file,
        MacroRefs const & macros,
        HeaderContent const & headerContent,
        Headers const & headers
    )
    {
        HeadersInfo::iterator iter( headersInfo().find( file->getName() ) );
        if ( iter == headersInfo().end() )
        {
            while ( headersInfoList_.size() > 1024 * 1 )
            {
                headersInfo_.erase( headersInfoList_.back().header() );
                headersInfoList_.pop_back();
            }
            headersInfoList_.push_front( HeaderInfo( file->getName(), 20 ) );
            std::pair<HeadersInfo::iterator, bool> const insertResult(
                headersInfo().insert( std::make_pair( file->getName(),
                headersInfoList_.begin() ) ) );
            assert( insertResult.second );
            iter = insertResult.first;
        }

        CacheEntryPtr result = CacheEntry::create( uniqueFileName(),
            macros, headerContent, headers );
        iter->second->insert( result );
        return result;
    }

    CacheEntryPtr findEntry
    (
        llvm::StringRef fileName,
        MacroState const & macroState
    );

    std::size_t hits() const { return hits_; }
    std::size_t misses() const { return misses_; }

private:
    std::string uniqueFileName();

private:
    struct HeadersInfoList : public boost::container::list<HeaderInfo> {};
    struct HeadersInfo : public std::unordered_map<std::string, HeadersInfoList::iterator> {};

    HeadersInfo const & headersInfo() const { return headersInfo_; }
    HeadersInfo       & headersInfo()       { return headersInfo_; }

private:
    HeadersInfoList headersInfoList_;
    HeadersInfo headersInfo_;
    std::size_t counter_;
    std::size_t hits_;
    std::size_t misses_;
};


//------------------------------------------------------------------------------
#endif