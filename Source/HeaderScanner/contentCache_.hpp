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

class Cache;

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
        checksum( other.checksum ),
        modified( other.modified )
    {
    }

    ContentEntry & operator=( ContentEntry && other )
    {
        buffer.reset( other.buffer.take() );
        checksum = other.checksum;
        modified = other.modified;
        return *this;
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

    ContentEntry const & getOrCreate( clang::FileManager &, clang::FileEntry const *, Cache & );

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
