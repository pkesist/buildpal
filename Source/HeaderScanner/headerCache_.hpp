//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef headerCache_HPP__A615CA5B_F047_45DE_8314_AF96E4F4FF86
#define headerCache_HPP__A615CA5B_F047_45DE_8314_AF96E4F4FF86
//------------------------------------------------------------------------------
#include "headerScanner_.hpp"

#include <boost/unordered_map.hpp>
#include <boost/unordered_set.hpp>
#include <boost/ptr_container/ptr_map.hpp>
#include <boost/thread/locks.hpp>
#include <boost/thread/lock_types.hpp> 
#include <boost/thread/recursive_mutex.hpp>

#include <string>
#include <map>
#include <set>
#include <vector>
//------------------------------------------------------------------------------

namespace clang
{
    class FileEntry;
}

typedef std::pair<llvm::StringRef, llvm::StringRef> StringPair;
typedef StringPair Macro;
typedef StringPair Header;
typedef std::set<StringPair> StringPairSet;
typedef StringPairSet Headers;
typedef StringPairSet Macros;
typedef std::map<llvm::StringRef, llvm::StringRef> MacroMap;

struct MacroUsage { enum Enum { used, defined, undefined }; };
typedef std::pair<MacroUsage::Enum, Macro> MacroWithUsage;
typedef std::vector<MacroWithUsage> MacroUsages;


class Cache
{
public:
    Cache() : counter_( 0 ) {}

    class CacheEntry
    {
    public:
        CacheEntry() {}

        CacheEntry
        (
            std::string const & uniqueVirtualFileName,
            MacroUsages const & macroUsagesp,
            Headers const & headersp
        ) : 
            fileName_( uniqueVirtualFileName ),
            macroUsages( macroUsagesp ),
            headers( headersp )
        {}

        CacheEntry( CacheEntry const & other )
        {
            this->operator=( other );
        }
            
        CacheEntry & operator=( CacheEntry const & other )
        {
            fileName_ = other.fileName_;
            macroUsages = other.macroUsages;
            headers = other.headers;

            if ( other.buffer_ )
            {
                llvm::StringRef const content( other.buffer_->getBufferStart(), other.buffer_->getBufferSize() );
                buffer_.reset( llvm::MemoryBuffer::getMemBufferCopy( content, "" ) );
            }
            return *this;
        }

        clang::FileEntry const * getFileEntry( clang::SourceManager & );
        void releaseFileEntry( clang::SourceManager & );

    private:
        std::string fileName_;
        llvm::OwningPtr<llvm::MemoryBuffer> buffer_;

    public:
        MacroUsages macroUsages;
        Headers headers;
    };

    struct HeaderInfo
    {
        typedef std::list<std::pair<Macros, CacheEntry> > CacheList;

        typedef CacheList::value_type CacheHit;

        HeaderInfo( std::size_t const size ) : size_( size ) {}

        CacheHit * find( clang::Preprocessor const & );
        void insert( Macros const & key, CacheEntry const & );

    private:
        CacheList cacheList_;
        std::size_t size_;
    };
    typedef HeaderInfo::CacheHit CacheHit;

    template <typename HeadersList>
    void addEntry
    (
        clang::FileEntry const * file,
        Macros const & macros,
        MacroUsages const & macroUsages,
        HeadersList const & headers
    )
    {
        // Exclusive ownership.
        boost::unique_lock<boost::recursive_mutex> const lock( mutex_ );

        HeadersInfo::iterator iter( headersInfo().find( file->getName() ) );
        if ( iter == headersInfo().end() )
        {
            while ( headersInfoList_.size() > 1024 * 4 )
            {
                HeadersInfoList::value_type const & val( headersInfoList_.back() );
                headersInfo_.erase( val.first );
                headersInfoList_.pop_back();
            }
            headersInfoList_.push_front( std::make_pair( file->getName(), HeaderInfo( 50 ) ) );
            std::pair<HeadersInfo::iterator, bool> const insertResult( headersInfo().insert( std::make_pair( file->getName(), headersInfoList_.begin() ) ) );
            assert( insertResult.second );
            iter = insertResult.first;
        }

        iter->second->second.insert
        (
            clone<Macros>( macros ),
            CacheEntry(
                uniqueFileName(),
                clone( macroUsages ),
                clone<Headers>( headers )
            )
        );
    }

    CacheHit * findEntry
    ( 
        llvm::StringRef fileName,
        clang::Preprocessor const &
    );

private:
    std::string uniqueFileName();

private:
    // Poor man's flyweight.
    llvm::StringRef cloneStr( llvm::StringRef x )
    {
        std::pair<FlyWeight::iterator, bool> insertResult( flyweight_.insert( x ) );
        return llvm::StringRef( insertResult.first->data(), insertResult.first->size() );
    }

    StringPair cloneStrPair( StringPair const & p )
    {
        return std::make_pair( cloneStr( p.first ), cloneStr( p.second ) );
    }

    MacroUsages clone( MacroUsages const & mu )
    {
        MacroUsages result;
        for ( MacroUsages::const_iterator iter( mu.begin() ); iter != mu.end(); ++iter )
            result.push_back( std::make_pair( iter->first, cloneStrPair( iter->second ) ) );
        return result;
    }
    
    template <typename Result, typename StringPairContainer>
    Result clone( StringPairContainer const & cont )
    {
        Result result;
        for ( StringPairContainer::const_iterator iter( cont.begin() ); iter != cont.end(); ++iter )
            result.insert( std::make_pair( cloneStr( iter->first ), cloneStr( iter->second ) ) );
        return result;
    }

private:
    struct HeadersInfoList : public std::list<std::pair<std::string, HeaderInfo> > {};
    struct HeadersInfo : public boost::unordered_map<std::string, HeadersInfoList::iterator> {};

    HeadersInfo const & headersInfo() const { return headersInfo_; }
    HeadersInfo       & headersInfo()       { return headersInfo_; }

    typedef boost::unordered_set<std::string> FlyWeight;

private:
    HeadersInfoList headersInfoList_;
    HeadersInfo headersInfo_;
    FlyWeight flyweight_;
    unsigned counter_;
    boost::recursive_mutex mutex_;
};


//------------------------------------------------------------------------------
#endif