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

class ContentEntry;
typedef boost::intrusive_ptr<ContentEntry> ContentEntryPtr;

class ContentEntry
{
private:
    ContentEntry( ContentEntry const & ); // = delete;
    ContentEntry & operator=( ContentEntry const & ); // = delete;

public:
    static llvm::ErrorOr<ContentEntryPtr> create( llvm::Twine const & path );

    std::size_t const size() const { return buffer->getBufferSize(); }

    std::unique_ptr<llvm::MemoryBuffer> buffer;
    std::size_t checksum;
    clang::vfs::Status status;

private:
    explicit ContentEntry( llvm::MemoryBuffer *, clang::vfs::Status const & );

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


//------------------------------------------------------------------------------
#endif
//------------------------------------------------------------------------------
