//------------------------------------------------------------------------------
#include "contentCache_.hpp"

#include "headerCache_.hpp"
#include "utility_.hpp"

#include <memory>
//------------------------------------------------------------------------------

llvm::ErrorOr<ContentEntryPtr> ContentCache::getOrCreate( llvm::Twine const & path )
{
    llvm::sys::fs::UniqueID uniqueID;
    std::error_code error = llvm::sys::fs::getUniqueID( path, uniqueID );
    if ( error )
        return error;

    typedef Content::index<ByFileId>::type ContentByFileId;
    {
        boost::shared_lock<boost::shared_mutex> readLock( contentMutex_ );
        ContentByFileId & contentByFileId( content_.get<ByFileId>() );
        ContentByFileId::const_iterator const iter( contentByFileId.find( uniqueID ) );
        if ( iter != contentByFileId.end() )
        {
            ContentEntryPtr contentEntryPtr = *iter;
            readLock.unlock();
            llvm::sys::fs::file_status currentStatus;
            if ( std::error_code const statusError = llvm::sys::fs::status( path, currentStatus ) )
                return statusError;
            if ( contentEntryPtr->status.getLastModificationTime() == currentStatus.getLastModificationTime() )
            {
                boost::unique_lock<boost::shared_mutex> const exclusiveLock( contentMutex_ );
                Content::iterator listIter = content_.project<0>( iter );
                content_.splice( content_.begin(), content_, listIter );
                return contentEntryPtr;
            }
            llvm::MemoryBuffer * buffer( prepareSourceFile( path ) );
            // Notify observers that this content entry is out of date.
            contentChanged_( *contentEntryPtr );
            boost::unique_lock<boost::shared_mutex> const exclusiveLock( contentMutex_ );
            ContentEntryPtr newPtr( new ContentEntry( uniqueID, buffer, currentStatus ) );
            contentByFileId.erase( iter );
            content_.push_front( newPtr );
            contentSize_ += newPtr->size();
            contentSize_ -= contentEntryPtr->size();
            return newPtr;
        }
    }
    llvm::sys::fs::file_status status;
    std::error_code const statusError = llvm::sys::fs::status( path, status );
    if ( statusError )
        return statusError;

    llvm::MemoryBuffer * buffer( prepareSourceFile( path ) );
    boost::upgrade_lock<boost::shared_mutex> upgradeLock( contentMutex_ );
    {
        // Preform another search with upgrade ownership.
        ContentByFileId & contentByFileId( content_.get<ByFileId>() );
        ContentByFileId::const_iterator const iter( contentByFileId.find( uniqueID ) );
        if ( iter != contentByFileId.end() )
            return *iter;
    }
    boost::upgrade_to_unique_lock<boost::shared_mutex> const exclusiveLock( upgradeLock );
    ContentEntryPtr newPtr( new ContentEntry( uniqueID, buffer, status ) );
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
