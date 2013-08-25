//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef headerCache_HPP__A615CA5B_F047_45DE_8314_AF96E4F4FF86
#define headerCache_HPP__A615CA5B_F047_45DE_8314_AF96E4F4FF86
//------------------------------------------------------------------------------
#include "headerScanner_.hpp"

#include <boost/variant.hpp>
#include <boost/container/list.hpp>
#include <boost/thread/locks.hpp>
#include <boost/thread/lock_types.hpp> 
#include <boost/thread/recursive_mutex.hpp>

#include <list>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>
//------------------------------------------------------------------------------

namespace clang
{
    class FileEntry;
}

typedef std::pair<std::string, std::string> StringPair;
typedef StringPair Macro;
typedef std::pair<std::string, clang::FileEntry const *> HeaderName;
typedef std::set<StringPair> StringPairSet;
typedef StringPairSet Macros;
typedef std::map<std::string, std::string> MacroMap;
struct MacroUsage { enum Enum { defined, undefined }; };
typedef std::pair<MacroUsage::Enum, Macro> MacroWithUsage;
class CacheEntry;
typedef boost::variant<HeaderName, std::shared_ptr<CacheEntry> > Header;
typedef std::vector<Header> Headers;
typedef boost::variant<MacroWithUsage, std::shared_ptr<CacheEntry> > HeaderEntry;
typedef std::vector<HeaderEntry> HeaderContent;

class CacheEntry
{
private:
    BOOST_MOVABLE_BUT_NOT_COPYABLE(CacheEntry)

public:
    CacheEntry
    (
        std::string const & uniqueVirtualFileName,
        Macros const & usedMacros,
        HeaderContent const & headerContent,
        Headers const & headers
    ) : 
        fileName_( uniqueVirtualFileName ),
        usedMacros_( usedMacros ),
        headerContent_( headerContent ),
        headers_( headers )
    {
    }

    CacheEntry( CacheEntry && other )
    {
        this->operator=( std::move( other ) );
    }
            
    CacheEntry & operator=( CacheEntry && other )
    {
        fileName_.swap( other.fileName_ );
        usedMacros_.swap( other.usedMacros_ );
        headerContent_.swap( other.headerContent_ );
        headers_.swap( other.headers_ );

        buffer_.reset( other.buffer_.take() );
        return *this;
    }

    clang::FileEntry const * getFileEntry( clang::SourceManager & );
    void releaseFileEntry( clang::SourceManager & );
    void generateContent();

    Macros        const & usedMacros   () const { return usedMacros_; }
    HeaderContent       & headerContent()       { return headerContent_; }
    HeaderContent const & headerContent() const { return headerContent_; }
    Headers       const & headers      () const { return headers_; }

private:
    std::string fileName_;
    llvm::OwningPtr<llvm::MemoryBuffer> buffer_;
    Macros usedMacros_;
    HeaderContent headerContent_;
    Headers headers_;
};


class Cache
{
public:
    Cache() : counter_( 0 ) {}

    typedef CacheEntry CacheEntry;

    class HeaderInfo
    {
    private:
        HeaderInfo( HeaderInfo const & );
        HeaderInfo & operator=( HeaderInfo & );

    public:
        typedef boost::container::list<std::shared_ptr<CacheEntry> > CacheList;

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

        std::shared_ptr<Cache::CacheEntry> find( clang::Preprocessor const & );
        std::shared_ptr<Cache::CacheEntry> insert( CacheEntry && );

        std::string const & header() const { return header_; }

    private:
        std::string header_;
        CacheList cacheList_;
    };

    std::shared_ptr<Cache::CacheEntry> addEntry
    (
        clang::FileEntry const * file,
        Macros const & macros,
        HeaderContent const & headerContent,
        Headers const & headers
    )
    {
        boost::unique_lock<boost::recursive_mutex> const lock( mutex_ );

        HeadersInfo::iterator iter( headersInfo().find( file->getName() ) );
        if ( iter == headersInfo().end() )
        {
            while ( headersInfoList_.size() > 1024 * 1 )
            {
                headersInfo_.erase( headersInfoList_.back().header() );
                headersInfoList_.pop_back();
            }
            headersInfoList_.push_front( HeaderInfo( file->getName(), 20 ) );
            std::pair<HeadersInfo::iterator, bool> const insertResult( headersInfo().insert( std::make_pair( file->getName(), headersInfoList_.begin() ) ) );
            assert( insertResult.second );
            iter = insertResult.first;
        }

        return iter->second->insert(
            CacheEntry( uniqueFileName(), macros, headerContent, headers ) );
    }

    std::shared_ptr<CacheEntry> findEntry
    ( 
        llvm::StringRef fileName,
        clang::Preprocessor const &
    );

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
    unsigned counter_;
    boost::recursive_mutex mutex_;
};


//------------------------------------------------------------------------------
#endif