//------------------------------------------------------------------------------
#include "headerCache_.hpp"
#include "headerTracker_.hpp"

#include <clang/Lex/Preprocessor.h>

#include <boost/spirit/include/karma.hpp>

#include <fstream>
//------------------------------------------------------------------------------

MacroValue undefinedMacroValue = MacroValue( llvm::StringRef( "", 1 ) );

clang::FileEntry const * CacheEntry::getFileEntry(
    clang::SourceManager & sourceManager )
{
    clang::FileEntry const * result(
        sourceManager.getFileManager().getVirtualFile( fileName_, 0, 0 ) );
    if ( !sourceManager.isFileOverridden( result ) )
        sourceManager.overrideFileContents( result, cachedContent(), true );
    return result;
}

CacheEntryPtr CacheTree::find( HeaderCtx const & headerCtx ) const
{
    CacheTree const * currentTree = this;
    while ( currentTree )
    {
        if ( currentTree->entry_ )
            return currentTree->entry_;
        CacheTree::Children::const_iterator const iter = currentTree->children_.find(
            headerCtx.getMacroValue( currentTree->macroName_ ) );
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
    std::for_each(
        undefinedMacros().begin(),
        undefinedMacros().end  (),
        [&]( MacroName macroName )
        {
            defineStream << "#undef " << macroName << '\n';
        }
    );
    std::for_each(
        definedMacros().begin(),
        definedMacros().end  (),
        [&]( MacroState::value_type const & macro )
        {
            defineStream << "#define " << macro.first << macro.second << '\n';
        }
    );
}

CacheEntry::CacheEntry
(
    CacheTree & tree,
    std::string const & uniqueVirtualFileName,
    MacroState && definedMacros,
    MacroNames && undefinedMacros,
    Headers && headers,
    std::size_t currentTime
) :
    tree_( tree ),
    refCount_( 0 ),
    fileName_( uniqueVirtualFileName ),
    undefinedMacros_( std::move( undefinedMacros ) ),
    definedMacros_( std::move( definedMacros ) ),
    headers_( std::move( headers ) ),
    lastTimeHit_( currentTime )
{
    contentLock_.clear();
}

CacheEntryPtr CacheEntry::create
(
    CacheTree & tree,
    std::string const & uniqueVirtualFileName,
    MacroState && definedMacros,
    MacroNames && undefinedMacros,
    Headers && headers,
    std::size_t currentTime
)
{
    return CacheEntryPtr
    (
        new CacheEntry
        (
            tree,
            uniqueVirtualFileName,
            std::move( definedMacros ),
            std::move( undefinedMacros ),
            std::move( headers ),
            currentTime
        )
    );
}


CacheEntryPtr Cache::addEntry
(
    llvm::sys::fs::UniqueID const & fileId,
    std::size_t searchPathId,
    UsedMacros && usedMacros,
    MacroState && definedMacros,
    MacroNames && undefinedMacros,
    Headers && headers
)
{
    boost::unique_lock<boost::shared_mutex> const lock( cacheMutex_ );
    CacheTree & cacheTree(
        cacheContainer_[ std::make_pair( fileId, searchPathId ) ].getChild(
        usedMacros ) );
    assert( !cacheTree.getEntry() );
    CacheEntryPtr result = CacheEntry::create( cacheTree, uniqueFileName(),
        std::move( definedMacros ), std::move( undefinedMacros ),
        std::move( headers ), ( hits_ + misses_ ) / 2 );
    cacheTree.setEntry( result );
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
    unsigned int const currentTime = hits_ + misses_;
    unsigned int const cacheCleanupPeriod = 1024 * 5;
    unsigned int const historyLength = 4 * cacheCleanupPeriod;
    if ( ( currentTime > historyLength ) && !( currentTime % cacheCleanupPeriod ) )
    {
        boost::unique_lock<boost::shared_mutex> const lock( cacheMutex_ );
        typedef CacheEntries::index<ByLastTimeHit>::type IndexType;
        IndexType & index( cacheEntries_.get<ByLastTimeHit>() );
        // Remove everything what was not hit in the last cacheCleanupPeriod tries.
        IndexType::iterator const end = index.lower_bound( currentTime - historyLength );
        std::for_each( index.begin(), end,
            [&]( CacheEntryPtr const & entry )
            {
                entry->detach();
            });
        index.erase( index.begin(), end );
    }
}

void Cache::invalidate( ContentEntry const & contentEntry )
{
    boost::unique_lock<boost::shared_mutex> const lock( cacheMutex_ );
    std::vector<CacheEntryPtr const *> entriesToRemove;
    std::for_each( cacheEntries_.begin(), cacheEntries_.end(),
        [&]( CacheEntryPtr const & entry )
        {
            if ( entry->usesBuffer( contentEntry.buffer.get() ) )
            {
                entry->detach();
                entriesToRemove.push_back( &entry );
            }
        });
    for ( CacheEntryPtr const * entry : entriesToRemove )
    {
        cacheEntries_.erase( cacheEntries_.iterator_to( *entry ) );
    }
}

CacheEntryPtr Cache::findEntry( llvm::sys::fs::UniqueID const & fileId,
    std::size_t searchPathId, HeaderCtx const & headerCtx )
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
        result = iter->second.find( headerCtx );
    }
    if ( result )
    {
        boost::upgrade_lock<boost::shared_mutex> upgradeLock( cacheMutex_ );
        // Note that we cannot use CacheContainer::iterator_to() to obtain
        // the iterator to update. iterator_to() needs a reference to the
        // actual value stored in the container, not a copy.
        typedef CacheEntries::index<ById>::type IndexByIdType;
        IndexByIdType & indexById( cacheEntries_.get<ById>() );
        IndexByIdType::iterator const iter = indexById.find( result.get() );
        if ( iter != indexById.end() )
        {
            unsigned int const currentTime = hits_ + misses_;
            boost::upgrade_to_unique_lock<boost::shared_mutex> const lock( upgradeLock );
            indexById.modify( iter, [=]( CacheEntryPtr p ) { p->cacheHit( currentTime ); } );
        }
        ++hits_;
    }
    else
        ++misses_;
    return result;
}


//------------------------------------------------------------------------------
