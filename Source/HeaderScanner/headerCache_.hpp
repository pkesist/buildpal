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
#include <boost/functional/hash.hpp>
#include <boost/thread/locks.hpp>
#include <boost/thread/lock_types.hpp> 

#include <llvm/ADT/StringMap.h>

#include <list>
#include <set>
#include <string>
#include <tuple>
#include <unordered_map>
#include <unordered_set>
#include <vector>
//------------------------------------------------------------------------------

namespace clang
{
    class FileEntry;
}

typedef std::pair<std::string, std::string> Macro;
typedef std::map<std::string, std::string> Macros;

typedef std::pair<llvm::StringRef, llvm::StringRef> MacroRef;
typedef std::map<llvm::StringRef, llvm::StringRef> MacroRefs;

struct MacroUsage { enum Enum { defined, undefined }; };
typedef std::pair<MacroUsage::Enum, Macro> MacroWithUsage;
class CacheEntry;
typedef boost::intrusive_ptr<CacheEntry> CacheEntryPtr;
typedef boost::variant<HeaderName, CacheEntryPtr> Header;
typedef std::vector<Header> Headers;
typedef boost::variant<MacroWithUsage, CacheEntryPtr> HeaderEntry;
typedef std::vector<HeaderEntry> HeaderContent;
typedef llvm::StringMap<llvm::StringRef, llvm::BumpPtrAllocator> MacroState;

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
        std::copy( usedMacros.begin(), usedMacros.end(),
            std::inserter( usedMacros_, usedMacros_.begin() ) );
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
    llvm::OwningPtr<llvm::MemoryBuffer> buffer_;
    Macros usedMacros_;
    HeaderContent headerContent_;
    Headers headers_;
    std::size_t refCount_;
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