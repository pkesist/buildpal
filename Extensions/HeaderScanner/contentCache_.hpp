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
#include <llvm/ADT/Hashing.h>
#include <llvm/ADT/SmallString.h>
#include <llvm/ADT/StringRef.h>
#include <llvm/Support/MemoryBuffer.h>

#include <unordered_map>
#include <memory>

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

    ContentEntryPtr getOrCreate( clang::FileManager &, clang::FileEntry const *, Cache * );

    void clear() { content_.clear(); }

public:
    static ContentCache & singleton() { return singleton_; }

private:
    static ContentCache singleton_;

private:
    mutable boost::shared_mutex contentMutex_;
    Content content_;
};


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
