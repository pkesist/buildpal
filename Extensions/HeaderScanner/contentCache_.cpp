//------------------------------------------------------------------------------
#include "contentCache_.hpp"

#include "headerCache_.hpp"
#include "utility_.hpp"

#include <memory>
//------------------------------------------------------------------------------

llvm::ErrorOr<clang::vfs::Status> ContentCache::status( llvm::Twine const & path )
{
    llvm::ErrorOr<ContentEntryPtr> contentEntry = getOrCreate( path );
    if ( contentEntry )
        return contentEntry.get()->status;
    llvm::sys::fs::file_status tmpStat;
    std::error_code error = llvm::sys::fs::status( path, tmpStat );
    if ( error )
        return error;
    clang::vfs::Status status( tmpStat );
    status.setName( path.str() );
    return status;
}

llvm::ErrorOr<ContentEntryPtr> ContentCache::addNewEntry( llvm::Twine const & path )
{
    llvm::ErrorOr<ContentEntryPtr> newPtrE = ContentEntry::create( path );
    if ( std::error_code ec = newPtrE.getError() )
        return ec;

    ContentEntryPtr const & newPtr = newPtrE.get();

    boost::upgrade_lock<boost::shared_mutex> upgradeLock( contentMutex_ );
    auto iter = content_.get<ByName>().find( path.str() );
    if ( iter != content_.get<ByName>().end() )
        return *iter;

    boost::upgrade_to_unique_lock<boost::shared_mutex> const exclusiveLock( upgradeLock );
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

llvm::ErrorOr<ContentEntryPtr> ContentCache::getOrCreate( llvm::Twine const & path )
{
    typedef Content::index<ByName>::type ContentByName;
    boost::shared_lock<boost::shared_mutex> readLock( contentMutex_ );
    ContentByName & contentByName( content_.get<ByName>() );
    ContentByName::const_iterator const iter( contentByName.find( path.str() ) );
    if ( iter == contentByName.end() )
    {
        readLock.unlock();
        return addNewEntry( path );
    }
    readLock.unlock();
    boost::unique_lock<boost::shared_mutex> const exclusiveLock( contentMutex_ );
    Content::iterator listIter = content_.project<0>( iter );
    content_.splice( content_.begin(), content_, listIter );
    return *iter;
}


//------------------------------------------------------------------------------
