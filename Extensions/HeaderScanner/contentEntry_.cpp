#include "contentEntry_.hpp"

#include <llvm/Support/MemoryBuffer.h>

#include <codecvt>

#if defined(_MSC_VER) || defined(__MINGW32__)
// needed for ::close()
#include <io.h>
// no idea, just copied from clang
#ifndef S_ISFIFO
#define S_ISFIFO(x) (0)
#endif
#endif
namespace
{
    #define BASE 65521UL
    #define NMAX 5552

    #define DO1(buf, i) { sum1 += (buf)[i]; sum2 += sum1; }
    #define DO2(buf, i) DO1(buf, i); DO1(buf, i + 1);
    #define DO4(buf, i) DO2(buf, i); DO2(buf, i + 2);
    #define DO8(buf, i) DO4(buf, i); DO4(buf, i + 4);
    #define DO16(buf) DO8(buf, 0); DO8(buf, 8);
    #define MOD(a) a %= BASE

    std::size_t bsc_adler32( char const * data, std::size_t size )
    {
        unsigned int sum1 = 1;
        unsigned int sum2 = 0;

        while (size >= NMAX)
        {
            for (int i = 0; i < NMAX / 16; ++i)
            {
                DO16(data); data += 16;
            }
            MOD(sum1); MOD(sum2); size -= NMAX;
        }

        while (size >= 16)
        {
            DO16(data); data += 16; size -= 16;
        }

        while (size > 0)
        {
            DO1(data, 0); data += 1; size -= 1;
        }

        MOD(sum1); MOD(sum2);

        return sum1 | (sum2 << 16);
    }


    ////////////////////////////////////////////////////////////////////////////
    //
    // adler32()
    // ---------
    //
    ////////////////////////////////////////////////////////////////////////////

    std::size_t adler32( llvm::MemoryBuffer const * buffer )
    {
        return bsc_adler32( buffer->getBufferStart(), buffer->getBufferSize() );
    }


    ////////////////////////////////////////////////////////////////////////////
    //
    // convertEncodingIfNeeded()
    // -------------------------
    //
    ////////////////////////////////////////////////////////////////////////////

    void convertEncodingIfNeeded( llvm::MemoryBuffer * & pMemoryBuffer )
    {
        // Clang supports UTF-8 only. We also want to support UTF-16.
        llvm::StringRef const data = pMemoryBuffer->getBuffer();

        bool const bigEndian( data.startswith("\xFE\xFF") );
        bool const littleEndian( data.startswith("\xFF\xFE") );
        if ( !bigEndian && !littleEndian )
            return;

        wchar_t const * start = reinterpret_cast<wchar_t const *>( data.data() + 2 );
        std::size_t const inputSize = ( data.size() - 2 ) / sizeof(wchar_t);
        std::vector<wchar_t> input( start, start + inputSize );

        // This can be written more tersly, but exactly one of these branches
        // is a no-op, so try to make it easy for the optimizer.
        if ( littleEndian )
        {
            for ( wchar_t & stride : input )
            {
                char const * bytePtr = reinterpret_cast<char const *>( &stride );
                stride = static_cast<wchar_t>( ( bytePtr[1] << 8 ) | bytePtr[0] );
            }
        }
        else
        {
            for ( wchar_t & stride : input )
            {
                char const * bytePtr = reinterpret_cast<char const *>( &stride );
                stride = static_cast<wchar_t>( ( bytePtr[0] << 8 ) | bytePtr[1] );
            }
        }
        std::wstring_convert<
            std::codecvt_utf8_utf16<wchar_t>
        > converter;
        std::string utf8( converter.to_bytes( &input[0], &input[0] + input.size() ) );
        utf8.push_back('\0');
        pMemoryBuffer = llvm::MemoryBuffer::getMemBufferCopy( utf8, "" );
    }


    ////////////////////////////////////////////////////////////////////////////
    //
    // openFile()
    // ----------
    //
    ////////////////////////////////////////////////////////////////////////////

    typedef std::pair<llvm::MemoryBuffer *, clang::vfs::Status> OpenFileResult;

    llvm::ErrorOr<OpenFileResult> openFile( llvm::Twine const & path )
    {
        llvm::sys::fs::file_status fstat;
        llvm::MemoryBuffer * buf;
        std::string name;
        {
            int fd;
            if ( std::error_code ec = llvm::sys::fs::openFileForRead( path, fd ) )
                return ec;
            struct CloseFile
            {
                CloseFile( int fd ) : fd_( fd ) {}
                ~CloseFile() { if ( fd_ != -1 ) close(); }

                std::error_code close()
                {
                    if ( ::_close( fd_ ) )
                        return std::error_code(errno, std::generic_category());
                    fd_ = -1;
                    return std::error_code();
                }

                int fd_;
            } closeFileGuard( fd );
            if ( std::error_code ec = llvm::sys::fs::status( fd, fstat ) )
                return ec;
            name = path.str();
            llvm::ErrorOr<std::unique_ptr<llvm::MemoryBuffer> > openFile = llvm::MemoryBuffer::getOpenFile( fd, name.c_str(), fstat.getSize(), false, false );
            if ( std::error_code error = openFile.getError() )
                return error;
            if ( std::error_code error = closeFileGuard.close() )
                return error;

            buf = openFile.get().release();
        }

        convertEncodingIfNeeded( buf );

        return std::make_pair
        (
            buf,
            clang::vfs::Status
            (
                name,
                name,
                fstat.getUniqueID(),
                fstat.getLastModificationTime(),
                fstat.getUser(),
                fstat.getGroup(),
                buf->getBufferSize(),
                fstat.type(),
                fstat.permissions()
            )
        );
    }
}

llvm::ErrorOr<ContentEntryPtr> ContentEntry::create( llvm::Twine const & path )
{
    llvm::ErrorOr<OpenFileResult> openResult( openFile( path ) );
    if ( std::error_code ec = openResult.getError() )
        return ec;

    return ContentEntryPtr( new ContentEntry( openResult.get().first, openResult.get().second ) );
}

ContentEntry::ContentEntry( llvm::MemoryBuffer * b, clang::vfs::Status const & stat )
    :
    refCount_( 0 ), buffer( b ), checksum( adler32( b ) ), status( stat )
{
}
