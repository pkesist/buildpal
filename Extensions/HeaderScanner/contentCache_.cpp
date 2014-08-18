//------------------------------------------------------------------------------
#include "contentCache_.hpp"

#include "headerCache_.hpp"
#include "utility_.hpp"
//------------------------------------------------------------------------------

ContentCache ContentCache::singleton_;

ContentEntryPtr ContentCache::getOrCreate( clang::FileManager & fm, clang::FileEntry const * file, Cache * cache )
{
    llvm::sys::fs::UniqueID const uniqueID = file->getUniqueID();
    typedef Content::index<ByFileId>::type ContentByFileId;
    {
        boost::shared_lock<boost::shared_mutex> readLock( contentMutex_ );
        ContentByFileId & contentByFileId( content_.get<ByFileId>() );
        ContentByFileId::const_iterator const iter( contentByFileId.find( uniqueID ) );
        if ( iter != contentByFileId.end() )
        {
            ContentEntryPtr contentEntryPtr = *iter;
            readLock.unlock();
            if ( contentEntryPtr->modified == file->getModificationTime() )
            {
                boost::unique_lock<boost::shared_mutex> const exclusiveLock( contentMutex_ );
                Content::iterator listIter = content_.project<0>( iter );
                content_.splice( content_.begin(), content_, listIter );
                return *iter;
            }
            if ( cache )
                cache->invalidate( *contentEntryPtr );
            llvm::MemoryBuffer * memoryBuffer( prepareSourceFile( fm, *file ) );
            boost::unique_lock<boost::shared_mutex> const exclusiveLock( contentMutex_ );
            ContentEntryPtr newPtr( new ContentEntry( uniqueID, memoryBuffer,
                file->getModificationTime() ) );
            contentByFileId.erase( iter );
            content_.push_front( newPtr );
            contentSize_ += newPtr->size() - contentEntryPtr->size();
            return newPtr;
        }
    }
    llvm::OwningPtr<llvm::MemoryBuffer> buffer( prepareSourceFile( fm, *file ) );
    boost::upgrade_lock<boost::shared_mutex> upgradeLock( contentMutex_ );
    {
        // Preform another search with upgrade ownership.
        ContentByFileId & contentByFileId( content_.get<ByFileId>() );
        ContentByFileId::const_iterator const iter( contentByFileId.find( uniqueID ) );
        if ( iter != contentByFileId.end() )
            return *iter;
    }
    boost::upgrade_to_unique_lock<boost::shared_mutex> const exclusiveLock( upgradeLock );
    ContentEntryPtr newPtr( ContentEntryPtr( new ContentEntry( uniqueID, buffer.take(),
        file->getModificationTime() ) ) );
    content_.push_front( newPtr );
    contentSize_ += newPtr->size();
    unsigned int const maxContentCacheSize = 100 * 1024 * 1024;
    while ( contentSize_ > maxContentCacheSize )
    {
        contentSize_ -= content_.back()->size();
        content_.pop_back();
    }
    return newPtr;
}


//------------------------------------------------------------------------------
