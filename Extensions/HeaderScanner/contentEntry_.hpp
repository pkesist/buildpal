//------------------------------------------------------------------------------
#ifndef contentEntry_HPP__F53E1B60_046C_42A4_9402_221805461FA9
#define contentEntry_HPP__F53E1B60_046C_42A4_9402_221805461FA9
//------------------------------------------------------------------------------
#include <boost/intrusive_ptr.hpp>

#include <llvm/Support/FileSystem.h>
#include <llvm/Support/MemoryBuffer.h>
#include <clang/Basic/VirtualFileSystem.h>

#include <atomic>
#include <ctime>
#include <memory>

class ContentEntry
{
private:
    ContentEntry( ContentEntry const & ); // = delete;
    ContentEntry & operator=( ContentEntry const & ); // = delete;

public:
    ContentEntry() : checksum( 0 ) {};

    ContentEntry
    (
        llvm::sys::fs::UniqueID id,
        llvm::MemoryBuffer *,
        llvm::sys::fs::file_status const &
    );

    ContentEntry( ContentEntry && other )
        :
        refCount_( 0 ),
        id_( other.id_ ),
        buffer( other.buffer.release() ),
        checksum( other.checksum ),
        status( other.status )
    {
    }

    ContentEntry & operator=( ContentEntry && other )
    {
        id_ = other.id_;
        buffer.reset( other.buffer.release() );
        checksum = other.checksum;
        status = other.status;
        return *this;
    }

    std::size_t const size() const { return buffer->getBufferSize(); }

    llvm::sys::fs::UniqueID id_;
    std::unique_ptr<llvm::MemoryBuffer> buffer;
    std::size_t checksum;
    clang::vfs::Status status;

private:
    mutable std::atomic<size_t> refCount_;

    friend void intrusive_ptr_add_ref( ContentEntry * );
    friend void intrusive_ptr_release( ContentEntry * );

    void addRef()
    {
        refCount_.fetch_add( 1, std::memory_order_relaxed );
    }

    void decRef()
    {
        if ( refCount_.fetch_sub( 1, std::memory_order_release ) == 1 )
        {
            std::atomic_thread_fence( std::memory_order_acquire );
            delete this;
        }
    }
};

inline void intrusive_ptr_add_ref( ContentEntry * c ) { c->addRef(); }
inline void intrusive_ptr_release( ContentEntry * c ) { c->decRef(); }

typedef boost::intrusive_ptr<ContentEntry> ContentEntryPtr;


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
