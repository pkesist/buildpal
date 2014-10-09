//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef contentCache_HPP__C53BAD49_7ABA_46DF_A686_C4D7B839AAA0
#define contentCache_HPP__C53BAD49_7ABA_46DF_A686_C4D7B839AAA0
//------------------------------------------------------------------------------
#include "contentEntry_.hpp"

#include <boost/thread/lock_algorithms.hpp>
#include <boost/thread/shared_mutex.hpp>
#include <boost/signals2/signal.hpp>
#include <boost/signals2/connection.hpp>

#include <boost/multi_index_container.hpp>
#include <boost/multi_index/hashed_index.hpp>
#include <boost/multi_index/sequenced_index.hpp>
#include <clang/Basic/FileManager.h>
#include <clang/Basic/FileSystemStatCache.h>
#include <clang/Basic/VirtualFileSystem.h>
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

struct GetFileId
{
    typedef llvm::sys::fs::UniqueID result_type;
    result_type operator()( ContentEntryPtr const & p ) const
    {
        return p->id_;
    }
};

struct ByFileId {};

struct CachedFile : public clang::vfs::File
{
    ContentEntryPtr content_;

    CachedFile( ContentEntryPtr content ) : content_( content ) {}

    llvm::ErrorOr<clang::vfs::Status> status() override { return content_->status; }

    std::error_code getBuffer
    (
        llvm::Twine const & name,
        std::unique_ptr<llvm::MemoryBuffer> & result,
        int64_t fileSize,
        bool requiresNullTerminator,
        bool isVolatile
    ) override
    {
        result.reset
        (
            llvm::MemoryBuffer::getMemBuffer
            (
                content_->buffer->getBuffer(),
                name.str(),
                requiresNullTerminator
            )
        );
        return std::error_code();
    }

    std::error_code close() override { return std::error_code(); }
    void setName( llvm::StringRef name ) override {}
};

class RealFSDirIter : public clang::vfs::detail::DirIterImpl
{
    std::string path_;
    llvm::sys::fs::directory_iterator iter_;

public:
    RealFSDirIter( llvm::Twine const & path, std::error_code & ec )
      : path_( path.str() ), iter_( path, ec )
    {
        if ( !ec && ( iter_ != llvm::sys::fs::directory_iterator() ) )
        {
            llvm::sys::fs::file_status s;
            ec = iter_->status( s );
            if ( !ec )
            {
                CurrentEntry = clang::vfs::Status( s );
                CurrentEntry.setName( iter_->path() );
            }
        }
    }

    std::error_code increment() override
    {
        std::error_code ec;
        iter_.increment( ec );
        if ( ec )
        {
            return ec;
        }
        else if ( iter_ == llvm::sys::fs::directory_iterator() )
        {
            CurrentEntry = clang::vfs::Status();
        }
        else
        {
            llvm::sys::fs::file_status s;
            ec = iter_->status( s );
            CurrentEntry = clang::vfs::Status( s );
            CurrentEntry.setName( iter_->path() );
        }
        return ec;
    }
};

class ContentCache : public clang::vfs::FileSystem
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

    llvm::ErrorOr<ContentEntryPtr> getOrCreate( llvm::Twine const & path );

    void clear()
    {
        boost::unique_lock<boost::shared_mutex> const exclusiveLock( contentMutex_ );
        content_.clear();
        contentSize_ = 0;
    }

    template <typename F>
    boost::signals2::connection registerFileChangedCallback( F & f )
    {
        return contentChanged_.connect( f );
    }

private:
    std::error_code openFileForRead( llvm::Twine const & path, std::unique_ptr<clang::vfs::File> & result ) override
    {
        llvm::sys::fs::UniqueID id;
        std::error_code error = llvm::sys::fs::getUniqueID( path, id );
        if ( error )
            return error;
        llvm::ErrorOr<ContentEntryPtr> contentEntry( getOrCreate( path ) );
        if ( contentEntry )
            result.reset( new CachedFile( contentEntry.get() ) );
        return contentEntry.getError();
    }

    clang::vfs::directory_iterator dir_begin( llvm::Twine const & dir, std::error_code & e ) override
    {
        return clang::vfs::directory_iterator( std::make_shared<RealFSDirIter>( dir, e ) );
    }

    llvm::ErrorOr<clang::vfs::Status> status( llvm::Twine const & path )
    {
        llvm::sys::fs::file_status stat;
        if ( std::error_code e = llvm::sys::fs::status( path, stat ) )
          return e;
        clang::vfs::Status result( stat );
        result.setName( path.str() );
        return result;
    }

public:
    static llvm::IntrusiveRefCntPtr<ContentCache> & ptr()
    {
        static llvm::IntrusiveRefCntPtr<ContentCache> cc( new ContentCache() );
        return cc;
    }

    static ContentCache & singleton()
    {
        return *ptr();
    }

private:
    mutable boost::shared_mutex contentMutex_;
    Content content_;
    std::size_t contentSize_;
    boost::signals2::signal<void ( ContentEntry const & )> contentChanged_;
};


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
