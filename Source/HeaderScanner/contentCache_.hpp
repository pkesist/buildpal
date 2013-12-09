//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef contentCache_HPP__C53BAD49_7ABA_46DF_A686_C4D7B839AAA0
#define contentCache_HPP__C53BAD49_7ABA_46DF_A686_C4D7B839AAA0
//------------------------------------------------------------------------------
#include <boost/thread/lock_algorithms.hpp>
#include <boost/thread/shared_mutex.hpp>

#include <clang/Basic/FileManager.h>
#include <llvm/ADT/Hashing.h>
#include <llvm/ADT/SmallString.h>
#include <llvm/ADT/StringRef.h>
#include <llvm/Support/MemoryBuffer.h>

#include <unordered_map>

struct HashUniqueFileId
{
    std::size_t operator()( llvm::sys::fs::UniqueID const & val )
    {
        return llvm::hash_combine
        (
            llvm::hash_value( val.getDevice() ),
            llvm::hash_value( val.getFile() )
        );
    }
};

class ContentEntry
{
private:
    ContentEntry( ContentEntry const & ); // = delete;
    ContentEntry & operator=( ContentEntry const & ); // = delete;

public:
    ContentEntry() : checksum( 0 ), modified( 0 ) {};

    ContentEntry( llvm::MemoryBuffer * buffer, time_t const modified );

    ContentEntry( ContentEntry && other )
        :
        buffer( other.buffer.take() ),
        checksum( checksum ),
        modified( modified )
    {
    }

    ContentEntry & operator=( ContentEntry && other )
    {
        buffer.reset( other.buffer.take() );
        checksum = other.checksum;
        modified = other.modified;
    }

    llvm::OwningPtr<llvm::MemoryBuffer> buffer;
    std::size_t checksum;
    std::time_t modified;
};

class ContentCache
{
public:
    typedef std::unordered_map<llvm::sys::fs::UniqueID, ContentEntry, HashUniqueFileId> ContentMap;
    
    ContentEntry const * get( llvm::sys::fs::UniqueID const & id ) const
    {
        boost::shared_lock<boost::shared_mutex> const readLock( contentMutex_ );
        ContentMap::const_iterator const iter( contentMap_.find( id ) );
        return iter != contentMap_.end() ? &iter->second : 0;
    }

    ContentEntry const & getOrCreate( clang::FileManager & fm, clang::FileEntry const * file )
    {
        // TODO: In case content entry is out of date update it.
        // If checksum mismatches - drop cache.
        llvm::sys::fs::UniqueID const uniqueID = file->getUniqueID();
        ContentEntry const  * contentEntry( get( uniqueID ) );
        if ( contentEntry )
            return *contentEntry;
        boost::upgrade_lock<boost::shared_mutex> upgradeLock( contentMutex_ );
        // Preform another search with upgrade ownership.
        ContentMap::const_iterator const iter( contentMap_.find( uniqueID ) );
        if ( iter != contentMap_.end() )
            return iter->second;
        llvm::MemoryBuffer * buffer = fm.getBufferForFile( file );
        assert( buffer );
        boost::upgrade_to_unique_lock<boost::shared_mutex> const exclusiveLock( upgradeLock );
        std::pair<ContentMap::iterator, bool> const insertResult(
            contentMap_.insert( std::make_pair( uniqueID,
            ContentEntry( buffer, file->getModificationTime() ) ) ) );
        return insertResult.first->second;
    }

public:
    static ContentCache & singleton() { return singleton_; }

private:
    static ContentCache singleton_;

private:
    mutable boost::shared_mutex contentMutex_;
    ContentMap contentMap_;
};


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
