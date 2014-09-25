//------------------------------------------------------------------------------
#include "headerCache_.hpp"
#include "headerTracker_.hpp"

#include <clang/Lex/Preprocessor.h>

#include <boost/spirit/include/karma.hpp>

#include <fstream>
//------------------------------------------------------------------------------

clang::FileEntry const * CacheEntry::getFileEntry(
    clang::SourceManager & sourceManager )
{
    clang::FileEntry const * result(
        sourceManager.getFileManager().getVirtualFile( fileName_, 0, 0 ) );
    if ( !sourceManager.isFileOverridden( result ) )
        sourceManager.overrideFileContents( result, cachedContent(), true );
    return result;
}

CacheEntryPtr CacheTree::find( MacroState const & macroState ) const
{
    CacheTree const * currentTree = this;
    while ( currentTree )
    {
        if ( currentTree->entry_ )
            return currentTree->entry_;
        CacheTree::Children::const_iterator const iter = currentTree->children_.find(
            macroState.getMacroValue( currentTree->macroName_ ) );
        if ( iter == currentTree->children_.end() )
            return CacheEntryPtr();
        currentTree = &iter->second;
    }
    return CacheEntryPtr();
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
        memoryBuffer_.reset( llvm::MemoryBuffer::getMemBuffer(
            buffer_, "", true ) );
    }
    return memoryBuffer_.get();
}

void CacheEntry::generateContent( std::string & buffer )
{
    llvm::raw_string_ostream defineStream( buffer );
    macroState().forEachMacro(
        [&]( Macro const & macro )
        {
            if ( macro.second == undefinedMacroValue )
                defineStream << "#undef " << macro.first << '\n';
            else
                defineStream << "#define " << macro.first << macro.second << '\n';
        }
    );
}

CacheEntry::CacheEntry
(
    CacheTree & tree,
    std::string const & uniqueVirtualFileName,
    MacroState && macroState,
    Headers && headers,
    std::size_t currentTime
) :
    tree_( tree ),
    refCount_( 0 ),
    fileName_( uniqueVirtualFileName ),
    macroState_( std::move( macroState ) ),
    headers_( std::move( headers ) ),
    lastTimeHit_( currentTime )
{
    contentLock_.clear();
}

CacheEntryPtr Cache::addEntry
(
    llvm::sys::fs::UniqueID const & fileId,
    std::size_t searchPathId,
    IndexedUsedMacros const & usedMacros,
    MacroState && macroState,
    Headers && headers
)
{
    boost::upgrade_lock<boost::shared_mutex> upgradeLock( cacheMutex_ );
    CacheTree & cacheTree(
        cacheContainer_[ std::make_pair( fileId, searchPathId ) ].getChild(
        usedMacros ) );
    CacheEntry * entry = cacheTree.getEntry();
    if ( entry )
        return CacheEntryPtr( entry );
    CacheEntryPtr result = CacheEntryPtr
    (
        new CacheEntry
        (
            cacheTree,
            uniqueFileName(),
            std::move( macroState ),
            std::move( headers ),
            ( hits_ + misses_ ) / 2
        )
    );
    boost::upgrade_to_unique_lock<boost::shared_mutex> lock( upgradeLock );
    cacheTree.setEntry( result.get() );
    cacheEntries_.insert( result );
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

void Cache::maintenance()
{
    unsigned int const cacheCleanupPeriod = 1024 * 2;
    unsigned int const currentTime = hits_ + misses_;
    if ( currentTime % cacheCleanupPeriod )
        return;

    // Update hit counts.
    boost::unique_lock<boost::shared_mutex> uniqueLock( cacheMutex_ );
    {
        boost::unique_lock<boost::mutex> tempLastTimeHitLock( tempLastTimeHitMutex_ );
        std::for_each( tempLastTimeHit_.begin(), tempLastTimeHit_.end(), [this]( std::pair<CacheEntryPtr, unsigned int> const & entry )
        {
            typedef CacheEntries::index<ById>::type IndexByIdType;
            // Note that we cannot use CacheContainer::iterator_to() to obtain
            // the iterator to update. iterator_to() needs a reference to the
            // actual value stored in the container, not a copy.
            IndexByIdType & indexById( cacheEntries_.get<ById>() );
            IndexByIdType::iterator const iter = indexById.find( entry.first.get() );
            if ( iter != indexById.end() )
                indexById.modify( iter, [=]( CacheEntryPtr p ) { p->setLastTimeHit( entry.second ); } );
        });
        tempLastTimeHit_.clear();
    }

    typedef CacheEntries::index<ByLastTimeHit>::type IndexType;
    IndexType & index( cacheEntries_.get<ByLastTimeHit>() );
    unsigned int const historyLength = 8 * cacheCleanupPeriod;
    unsigned int const cutoffTime(
        currentTime > historyLength
            ? currentTime - historyLength
            : currentTime / 5
    );
    // Remove everything what was not hit since cutoffTime.
    index.erase( index.begin(), index.lower_bound( cutoffTime ) );
}

void Cache::invalidate( ContentEntry const & contentEntry )
{
    std::vector<CacheEntryPtr const *> entriesToRemove;
    boost::upgrade_lock<boost::shared_mutex> upgradeLock( cacheMutex_ );
    std::for_each( cacheEntries_.begin(), cacheEntries_.end(),
        [&]( CacheEntryPtr const & entry )
        {
            if ( entry->usesBuffer( contentEntry.buffer.get() ) )
            {
                entriesToRemove.push_back( &entry );
            }
        });
    if ( entriesToRemove.empty() )
        return;
    boost::upgrade_to_unique_lock<boost::shared_mutex> const lock( upgradeLock );
    for ( CacheEntryPtr const * entry : entriesToRemove )
        cacheEntries_.erase( cacheEntries_.iterator_to( *entry ) );
}

CacheEntryPtr Cache::findEntry( llvm::sys::fs::UniqueID const & fileId,
    std::size_t searchPathId, MacroState const & macroState )
{
    struct CacheMaintenance
    {
        Cache & cache_;
        CacheMaintenance( Cache & cache ) : cache_( cache ) {}
        ~CacheMaintenance() { cache_.maintenance(); }
    } maintenanceGuard( *this );

    CacheEntryPtr result;
    {
        boost::shared_lock<boost::shared_mutex> const lock( cacheMutex_ );
        CacheContainer::const_iterator const iter = cacheContainer_.find(
            std::make_pair( fileId, searchPathId ) );
        if ( iter == cacheContainer_.end() )
        {
            ++misses_;
            return CacheEntryPtr();
        }
        result = iter->second.find( macroState );
    }
    if ( result )
    {
        boost::unique_lock<boost::mutex> tempLastTimeHitLock( tempLastTimeHitMutex_ );
        tempLastTimeHit_[ result ] = hits_ + misses_;
        ++hits_;
    }
    else
        ++misses_;
    return result;
}


//------------------------------------------------------------------------------
