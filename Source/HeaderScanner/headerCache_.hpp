//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef headerCache_HPP__A615CA5B_F047_45DE_8314_AF96E4F4FF86
#define headerCache_HPP__A615CA5B_F047_45DE_8314_AF96E4F4FF86
//------------------------------------------------------------------------------
#include "headerScanner_.hpp"

#include <boost/variant.hpp>
#include <boost/container/list.hpp>
#include <boost/unordered_map.hpp>
#include <boost/unordered_set.hpp>
#include <boost/shared_ptr.hpp>
#include <boost/thread/locks.hpp>
#include <boost/thread/lock_types.hpp> 
#include <boost/thread/recursive_mutex.hpp>
#include <boost/move/move.hpp>


#include <list>
#include <map>
#include <set>
#include <string>
#include <vector>
//------------------------------------------------------------------------------

namespace clang
{
    class FileEntry;
}

typedef std::pair<std::string, std::string> StringPair;
typedef StringPair Macro;
typedef StringPair HeaderName;
typedef std::set<StringPair> StringPairSet;
typedef StringPairSet Macros;
typedef std::map<std::string, std::string> MacroMap;
struct MacroUsage { enum Enum { defined, undefined }; };
typedef std::pair<MacroUsage::Enum, Macro> MacroWithUsage;
class CacheEntry;
typedef boost::variant<HeaderName, boost::shared_ptr<CacheEntry> > Header;
typedef std::vector<Header> Headers;
typedef boost::variant<MacroWithUsage, boost::shared_ptr<CacheEntry> > HeaderEntry;
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

    CacheEntry( BOOST_RV_REF(CacheEntry) other )
    {
        this->operator=( boost::move( other ) );
    }
            
    CacheEntry & operator=( BOOST_RV_REF(CacheEntry) other )
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

    Macros const & usedMacros() const { return usedMacros_; }
    HeaderContent       & headerContent()       { return headerContent_; }
    HeaderContent const & headerContent() const { return headerContent_; }
    Headers const & headers() const { return headers_; }

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
        BOOST_MOVABLE_BUT_NOT_COPYABLE(HeaderInfo)

    public:
        typedef boost::container::list<boost::shared_ptr<CacheEntry> > CacheList;

        HeaderInfo( std::string const & header, std::size_t const size )
            :
            header_( header )
        {}

        HeaderInfo( BOOST_RV_REF(HeaderInfo) other )
            :
            cacheList_( boost::move( other.cacheList_ ) )
        {
            header_.swap( other.header_ );
        }

        HeaderInfo & operator=( BOOST_RV_REF(HeaderInfo) other )
        {
            header_.swap( other.header_ );
            cacheList_ = boost::move( other.cacheList_ );
        }

        boost::shared_ptr<Cache::CacheEntry> find( clang::Preprocessor const & );
        boost::shared_ptr<Cache::CacheEntry> insert( BOOST_RV_REF(CacheEntry) );

        std::string const & header() const { return header_; }

    private:
        std::string header_;
        CacheList cacheList_;
    };

    boost::shared_ptr<Cache::CacheEntry> addEntry
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
            while ( headersInfoList_.size() > 1024 * 4 )
            {
                headersInfo_.erase( headersInfoList_.back().header() );
                headersInfoList_.pop_back();
            }
            HeaderInfo tmp( file->getName(), 50 );
            headersInfoList_.push_front( boost::move( tmp ) );
            std::pair<HeadersInfo::iterator, bool> const insertResult( headersInfo().insert( std::make_pair( file->getName(), headersInfoList_.begin() ) ) );
            assert( insertResult.second );
            iter = insertResult.first;
        }

        CacheEntry cacheEntry
        (
            uniqueFileName(),
            macros,
            headerContent,
            headers
        );

        return iter->second->insert( boost::move( cacheEntry ) );
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

    template <typename StrPairCloner>
    struct HeaderContentInserter
    {
        typedef void result_type;

        HeaderContentInserter( HeaderContent & result, StrPairCloner strPairCloner ) :
            result_( result ), strPairCloner_( strPairCloner )
        {}

        void operator()( MacroWithUsage const & mwu )
        {
            result_.push_back( std::make_pair( mwu.first, strPairCloner_( mwu.second ) ) );
        }

        void operator()( boost::shared_ptr<CacheEntry> const & ce )
        {
            result_.push_back( ce );
        }

        HeaderContent & result_;
        StrPairCloner strPairCloner_;
    };

    template <typename StrPairCloner>
    static HeaderContentInserter<StrPairCloner> makeHeaderContentInserter( HeaderContent & result, StrPairCloner strPairCloner )
    {
        return HeaderContentInserter<StrPairCloner>( result, strPairCloner );
    }

    HeaderContent cloneHeaderContent( HeaderContent const & hc )
    {
        HeaderContent result;
        auto inserter( makeHeaderContentInserter( result, [this]( StringPair const & p ) { return cloneStrPair( p ); } ) );
        std::for_each( hc.begin(), hc.end(), [&]( HeaderEntry const & he ) { boost::apply_visitor( inserter, he ); } );
        return result;
    }

    template <typename StrPairCloner>
    struct HeaderNameInserter
    {
        typedef void result_type;

        HeaderNameInserter( Headers & result, StrPairCloner strPairCloner ) :
            result_( result ), strPairCloner_( strPairCloner )
        {}

        void operator()( HeaderName const & hn )
        {
            std::cout << "Inserting into cache " << std::string( hn.first ) << ' ' << std::string( hn.second ) << '\n';
            result_.push_back( strPairCloner_( hn ) );
        }

        void operator()( boost::shared_ptr<CacheEntry> const & ce )
        {
            result_.push_back( ce );
        }

        Headers & result_;
        StrPairCloner strPairCloner_;
    };

    template <typename StrPairCloner>
    static HeaderNameInserter<StrPairCloner> makeHeaderNameInserter( Headers & result, StrPairCloner strPairCloner )
    {
        return HeaderNameInserter<StrPairCloner>( result, strPairCloner );
    }

    template <typename StringPairContainer>
    Headers cloneHeaderNames( StringPairContainer const & cont )
    {
        Headers result;
        auto inserter( makeHeaderNameInserter( result, [this]( StringPair const & p ) { return cloneStrPair( p ); } ) );
        std::for_each( cont.begin(), cont.end(), [&]( Header const & h ) { boost::apply_visitor( inserter, h ); } );
        return result;
    }

    template <typename StringPairContainer>
    StringPairSet clone( StringPairContainer const & cont )
    {
        StringPairSet result;
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