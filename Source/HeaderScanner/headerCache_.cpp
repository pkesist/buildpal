//------------------------------------------------------------------------------
#include "headerCache_.hpp"
#include "headerTracker_.hpp"

#include <clang/Lex/Preprocessor.h>

#include <boost/spirit/include/karma.hpp>

#include <fstream>
//------------------------------------------------------------------------------

MacroValue undefinedMacroValue = MacroValue( llvm::StringRef( "", 1 ) );

clang::FileEntry const * CacheEntry::getFileEntry( clang::SourceManager & sourceManager )
{
    clang::FileEntry const * result( sourceManager.getFileManager().getVirtualFile( fileName_, 0, 0 ) );
    if ( !sourceManager.isFileOverridden( result ) )
        sourceManager.overrideFileContents( result, cachedContent(), true );
    return result;
}

llvm::MemoryBuffer const * CacheEntry::cachedContent()
{
    if ( !memoryBuffer_ )
    {
        std::string tmp;
        generateContent( tmp );

        // Two threads concurrently generating content for the same cache
        // entry should be a rare occasion, so spinlock.
        struct SpinLock
        {
            std::atomic_flag & mutex_;
            SpinLock( std::atomic_flag & mutex ) : mutex_( mutex )
            {
                while ( mutex_.test_and_set( std::memory_order_acquire ) );
            }

            ~SpinLock()
            {
                mutex_.clear( std::memory_order_release );
            }
        } const spinLock( contentLock_ );
        if ( memoryBuffer_ )
            return memoryBuffer_.get();
        buffer_.swap( tmp );
        memoryBuffer_.reset( llvm::MemoryBuffer::getMemBuffer( buffer_, "", true ) );
    }
    return memoryBuffer_.get();
}

void CacheEntry::generateContent( std::string & buffer )
{
    llvm::raw_string_ostream defineStream( buffer );
    std::for_each(
        headerContent().begin(),
        headerContent().end(),
        [&]( HeaderEntry const & he )
        {
            switch ( he.first )
            {
            case MacroUsage::defined:
                defineStream << "#define " << he.second.first << he.second.second << '\n';
                break;
            case MacroUsage::undefined:
                defineStream << "#undef " << he.second.first << '\n';
                break;
            }
        }
    );
    defineStream.flush();
}

CacheEntryPtr Cache::addEntry
(
    llvm::sys::fs::UniqueID const & fileId,
    std::size_t searchPathId,
    Macros && macros,
    HeaderContent && headerContent,
    Headers const & headers
)
{
    CacheEntryPtr result = CacheEntry::create( fileId, searchPathId, uniqueFileName(),
        std::move( macros ), std::move( headerContent ), headers, hits_ + misses_ );
    boost::unique_lock<boost::shared_mutex> const lock( cacheMutex_ );
    auto insertResult = cacheContainer_.insert( result );
    assert( insertResult.second );
    return result;
}

std::string Cache::uniqueFileName()
{
    std::string result;
    using namespace boost::spirit::karma;
    generate( std::back_inserter( result ),
        lit( "__cached_file_" ) << uint_,
        counter_.fetch_add( 1, std::memory_order_relaxed ) );
    return result;
}

void Cache::cleanup()
{
    unsigned int const currentTime = hits_ + misses_;
    unsigned int const cacheCleanupPeriod = 1024 * 5;
    unsigned int const historyLength = 4 * cacheCleanupPeriod;
    if ( ( currentTime > historyLength ) && !( currentTime % cacheCleanupPeriod ) )
    {
        boost::unique_lock<boost::shared_mutex> const lock( cacheMutex_ );
        typedef CacheContainer::index<ByLastTimeHit>::type IndexType;
        IndexType & index( cacheContainer_.get<ByLastTimeHit>() );
        // Remove everything what was not hit in the last cacheCleanupPeriod tries.
        IndexType::iterator const end = index.lower_bound( currentTime - historyLength );
        index.erase( index.begin(), end );
    }
}

void Cache::invalidate( ContentEntry const & contentEntry )
{
    boost::unique_lock<boost::shared_mutex> const lock( cacheMutex_ );
    std::vector<CacheEntryPtr const *> entriesToRemove;
    std::for_each( cacheContainer_.begin(), cacheContainer_.end(),
        [&]( CacheEntryPtr const & entry )
        {
            if ( entry->usesBuffer( contentEntry.buffer.get() ) )
                entriesToRemove.push_back( &entry );
        });
    for ( CacheEntryPtr const * entry : entriesToRemove )
        cacheContainer_.erase( cacheContainer_.iterator_to( *entry ) );
}

CacheEntryPtr Cache::findEntry( llvm::sys::fs::UniqueID const & fileId, std::size_t searchPathId, HeaderCtx const & headerCtx )
{
    struct CleanupOnExit
    {
        Cache & cache_;
        CleanupOnExit( Cache & cache ) : cache_( cache ) {}
        ~CleanupOnExit()
        {
            cache_.cleanup();
        }
    } cleanup( *this );
    std::vector<CacheEntryPtr> entriesForUid;
    {
        boost::shared_lock<boost::shared_mutex> const lock( cacheMutex_ );
        std::pair<CacheContainer::iterator, CacheContainer::iterator> const iterRange =
            cacheContainer_.equal_range( boost::make_tuple( fileId, searchPathId ) );
        std::copy( iterRange.first, iterRange.second, std::back_inserter( entriesForUid ) );
    }

    struct MacroMatchesState
    {
        explicit MacroMatchesState( HeaderCtx const & headerCtx ) : headerCtx_( headerCtx ) {}

        bool operator()( Macro const & macro ) const
        {
            return headerCtx_.getMacroValue( macro.first ) == macro.second;
        }

        HeaderCtx const & headerCtx_;
    };

    for ( CacheEntryPtr pEntry : entriesForUid )
    {
        if
        (
            std::find_if_not
            (
                pEntry->usedMacros().begin(),
                pEntry->usedMacros().end(),
                MacroMatchesState( headerCtx )
            ) == pEntry->usedMacros().end()
        )
        {
            boost::upgrade_lock<boost::shared_mutex> upgradeLock( cacheMutex_ );
            // Note that we cannot use CacheContainer::iterator_to() to obtain
            // the iterator to update. iterator_to() needs a reference to the
            // actual value stored in the container, not a copy.
            typedef CacheContainer::index<ById>::type IndexByIdType;
            IndexByIdType & indexById( cacheContainer_.get<ById>() );
            IndexByIdType::iterator const iter = indexById.find( &*pEntry );
            if ( iter != indexById.end() )
            {
                boost::upgrade_to_unique_lock<boost::shared_mutex> const lock( upgradeLock );
                unsigned int const currentTime = hits_ + misses_;
                indexById.modify( iter, [=]( CacheEntryPtr p ) { p->cacheHit( currentTime ); } );
            }
            ++hits_;
            return pEntry;
        }
    }
    ++misses_;
    return CacheEntryPtr();
}


//------------------------------------------------------------------------------
