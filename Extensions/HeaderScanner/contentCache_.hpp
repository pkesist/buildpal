//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef contentCache_HPP__C53BAD49_7ABA_46DF_A686_C4D7B839AAA0
#define contentCache_HPP__C53BAD49_7ABA_46DF_A686_C4D7B839AAA0
//------------------------------------------------------------------------------
#include "contentEntry_.hpp"

#include <boost/thread/lock_algorithms.hpp>
#include <boost/thread/shared_mutex.hpp>

#include <boost/multi_index_container.hpp>
#include <boost/multi_index/hashed_index.hpp>
#include <boost/multi_index/sequenced_index.hpp>
#include <clang/Basic/FileManager.h>
#include <clang/Basic/FileSystemStatCache.h>
#include <llvm/ADT/Hashing.h>
#include <llvm/ADT/SmallString.h>
#include <llvm/ADT/StringRef.h>
#include <llvm/Support/MemoryBuffer.h>

#include <unordered_map>
#include <memory>
#include <chrono>

struct HashUniqueFileId
{
    std::size_t operator()( llvm::sys::fs::UniqueID const & val ) const
    {
        return llvm::hash_combine
        (
            llvm::hash_value( val.getDevice() ),
            llvm::hash_value( val.getFile() )
        );
    }
};

class Cache;

struct GetFileId
{
    typedef llvm::sys::fs::UniqueID result_type;
    result_type operator()( ContentEntryPtr p ) const
    {
        return p->id_;
    }
};

struct ByFileId {};

struct PrevStatCalls
{
    struct StatCallEntry
    {
        clang::FileData fileData;
        std::chrono::steady_clock::time_point timeObtained;
    };

    typedef llvm::StringMap<StatCallEntry, llvm::BumpPtrAllocator> StatCalls;
    StatCalls statCalls_;
    boost::shared_mutex statMutex_;

    bool getStat( char const * path, clang::FileData & fileData, std::chrono::steady_clock::time_point const & currentTime )
    {
        boost::shared_lock<boost::shared_mutex> sharedLock( statMutex_ );
        StatCalls::const_iterator iter( statCalls_.find( path ) );
        if ( iter != statCalls_.end() )
        {
            std::chrono::duration<int, std::chrono::steady_clock::period> const obtainedBefore = currentTime - iter->getValue().timeObtained;
            if ( obtainedBefore.count() > 30 )
                return false;
            fileData = iter->getValue().fileData;
            return true;
        }
        return false;
    }

    void storeStat( char const * path, clang::FileData const & fileData, std::chrono::steady_clock::time_point const & currentTime )
    {
        boost::unique_lock<boost::shared_mutex> uniqueLock( statMutex_ );
        StatCallEntry entry = { fileData, currentTime };
        statCalls_[ path ] = entry;
    }
};


struct StatCache : public clang::FileSystemStatCache
{
    explicit StatCache( PrevStatCalls & prevStatCalls )
        : prevStatCalls_( prevStatCalls ) 
    {
    }

    // Prevent FileManager, HeaderSearch et al. to open files
    // unexpectedly.
    virtual clang::MemorizeStatCalls::LookupResult
        getStat( char const * path, clang::FileData & fileData, bool isFile,
        int * fileDesc ) LLVM_OVERRIDE
    {
        std::chrono::steady_clock::time_point currentTime = std::chrono::steady_clock::now();
        if ( isFile && prevStatCalls_.getStat( path, fileData, currentTime ) )
            return CacheExists;

        LookupResult result = statChained( path, fileData, isFile, fileDesc );
        if ( isFile && ( result == CacheExists ) )
            prevStatCalls_.storeStat( path, fileData, currentTime );
        return result;
    }

    PrevStatCalls & prevStatCalls_;
};


class ContentCache
{
public:
    typedef boost::multi_index_container<
        ContentEntryPtr,
        boost::multi_index::indexed_by<
            boost::multi_index::sequenced<>,
            boost::multi_index::hashed_unique<
                boost::multi_index::tag<ByFileId>,
                GetFileId,
                HashUniqueFileId
            >
        >
    > Content;

    ContentCache() : contentSize_( 0 ) {}

    ContentEntryPtr getOrCreate( clang::FileManager &, clang::FileEntry const *, Cache * );

    PrevStatCalls & prevStatCalls() { return prevStatCalls_; }

    void clear() { content_.clear(); }

public:
    static ContentCache & singleton() { return singleton_; }

private:
    static ContentCache singleton_;

private:
    mutable boost::shared_mutex contentMutex_;
    PrevStatCalls prevStatCalls_;
    Content content_;
    std::size_t contentSize_;
};


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
