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

class ContentCache
{
public:
    typedef std::unordered_map<llvm::sys::fs::UniqueID, llvm::MemoryBuffer const *, HashUniqueFileId> ContentMap;
    
    ContentCache() : size_( 0 ) {}

    ~ContentCache()
    {
        for ( auto & value : contentMap_ )
            delete value.second;
    }

    llvm::MemoryBuffer const * get( llvm::sys::fs::UniqueID const & id ) const
    {
        boost::shared_lock<boost::shared_mutex> const readLock( contentMutex_ );
        ContentMap::const_iterator const iter( contentMap_.find( id ) );
        return iter != contentMap_.end() ? iter->second : 0;
    }

    llvm::MemoryBuffer const * getOrCreate( clang::FileManager & fm, clang::FileEntry const * file )
    {
        llvm::sys::fs::UniqueID const uniqueID = file->getUniqueID();
        llvm::MemoryBuffer const * buffer( get( uniqueID ) );
        if ( buffer )
            return buffer;
        boost::upgrade_lock<boost::shared_mutex> upgradeLock( contentMutex_ );
        // Preform another search with upgrade ownership.
        ContentMap::const_iterator const iter( contentMap_.find( uniqueID ) );
        if ( iter != contentMap_.end() )
            return iter->second;
        buffer = fm.getBufferForFile( file );
        assert( buffer );
        boost::upgrade_to_unique_lock<boost::shared_mutex> const exclusiveLock( upgradeLock );
        contentMap_.insert( std::make_pair( uniqueID, buffer ) );
        size_ += buffer->getBufferSize();
        return buffer;
    }

public:
    static ContentCache & singleton() { return singleton_; }

private:
    static ContentCache singleton_;

private:
    mutable boost::shared_mutex contentMutex_;
    ContentMap contentMap_;
    std::size_t size_;
};


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
