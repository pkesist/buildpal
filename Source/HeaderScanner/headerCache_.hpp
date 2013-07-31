//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef headerCache_HPP__A615CA5B_F047_45DE_8314_AF96E4F4FF86
#define headerCache_HPP__A615CA5B_F047_45DE_8314_AF96E4F4FF86
//------------------------------------------------------------------------------
#include "headerScanner_.hpp"

#include <boost/container/list.hpp>
#include <boost/unordered_map.hpp>
#include <boost/unordered_set.hpp>
#include <boost/shared_ptr.hpp>
#include <boost/thread/locks.hpp>
#include <boost/thread/lock_types.hpp> 
#include <boost/thread/recursive_mutex.hpp>
#include <boost/move/move.hpp>


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
    private:
        BOOST_MOVABLE_BUT_NOT_COPYABLE(CacheEntry)

    public:
        CacheEntry
        (
            std::string const & uniqueVirtualFileName,
            Macros const & usedMacros,
            MacroUsages const & macroUsages,
            Headers const & headers
        ) : 
            fileName_( uniqueVirtualFileName ),
            usedMacros_( usedMacros ),
            macroUsages_( macroUsages ),
            headers_( headers )
        {
        }

        CacheEntry( BOOST_RV_REF(CacheEntry) other )
        {
            this->operator=( boost::move( other ) );
        }
            
        CacheEntry & operator=( BOOST_RV_REF(CacheEntry) other )
        {
            fileName_.swap( other.fileName_ );
            usedMacros_.swap( other.usedMacros_ );
            macroUsages_.swap( other.macroUsages_ );
            headers_.swap( other.headers_ );

            buffer_.reset( other.buffer_.take() );
            return *this;
        }

        clang::FileEntry const * getFileEntry( clang::SourceManager & );
        void releaseFileEntry( clang::SourceManager & );
        void generateContent( boost::recursive_mutex & );

        Macros const & usedMacros() const { return usedMacros_; }
        MacroUsages const & macroUsages() const { return macroUsages_; }
        Headers const & headers() const { return headers_; }

    private:
        std::string fileName_;
        llvm::OwningPtr<llvm::MemoryBuffer> buffer_;
        Macros usedMacros_;
        MacroUsages macroUsages_;
        Headers headers_;
    };

    class HeaderInfo
    {
    private:
        BOOST_MOVABLE_BUT_NOT_COPYABLE(HeaderInfo)

    public:
        typedef boost::container::list<boost::shared_ptr<CacheEntry> > CacheList;

        HeaderInfo( std::string const & header, std::size_t const size )
            :
            header_( header ), disabled_( false )
        {}

        HeaderInfo( BOOST_RV_REF(HeaderInfo) other )
            :
            cacheList_( boost::move( other.cacheList_ ) ),
            disabled_( other.disabled_ )
        {
            header_.swap( other.header_ );
        }

        void disable()
        {
            disabled_ = true;
            cacheList_.clear();
        }

        HeaderInfo & operator=( BOOST_RV_REF(HeaderInfo) other )
        {
            header_.swap( other.header_ );
            cacheList_ = boost::move( other.cacheList_ );
        }

        boost::shared_ptr<Cache::CacheEntry> find( clang::Preprocessor const & );
        void insert( BOOST_RV_REF(CacheEntry) );

        bool disabled() const { return disabled_; }
        std::string const & header() const { return header_; }

        boost::recursive_mutex & generateMutex() { return generateMutex_; }

    private:
        std::string header_;
        boost::recursive_mutex generateMutex_;
        CacheList cacheList_;
        bool disabled_;
    };

    template <typename HeadersList>
    void addEntry
    (
        clang::FileEntry const * file,
        Macros const & macros,
        MacroUsages const & macroUsages,
        HeadersList const & headers
    )
    {
        if ( macros.size() > 20 )
            return;

        boost::unique_lock<boost::recursive_mutex> const lock( mutex_ );

        HeadersInfo::iterator iter( headersInfo().find( file->getName() ) );
        if ( iter == headersInfo().end() )
        {
            while ( headersInfoList_.size() > 1024 * 4 )
            {
                headersInfo_.erase( headersInfoList_.back().header() );
                headersInfoList_.pop_back();
            }
            HeaderInfo tmp( file->getName(), 20 );
            headersInfoList_.push_front( boost::move( tmp ) );
            std::pair<HeadersInfo::iterator, bool> const insertResult( headersInfo().insert( std::make_pair( file->getName(), headersInfoList_.begin() ) ) );
            assert( insertResult.second );
            iter = insertResult.first;
        }
        if ( iter->second->disabled() )
            return;

        CacheEntry cacheEntry
        (
            uniqueFileName(),
            clone<Macros>( macros ),
            clone( macroUsages ),
            clone<Headers>( headers )
        );

        iter->second->insert( boost::move( cacheEntry ) );
    }

    boost::shared_ptr<CacheEntry> findEntry
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
        std::pair<FlyWeight::iterator, bool> const insertResult( flyweight_.insert( x ) );
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
    struct HeadersInfoList : public boost::container::list<HeaderInfo> {};
    struct HeadersInfo : public boost::unordered_map<std::string, HeadersInfoList::iterator>
    {};

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