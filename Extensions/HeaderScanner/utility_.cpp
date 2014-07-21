#include "utility_.hpp"

#include <llvm/Support/MemoryBuffer.h>

#include <codecvt>

namespace
{
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
        delete pMemoryBuffer;
        pMemoryBuffer = llvm::MemoryBuffer::getMemBufferCopy( utf8, "" );
    }
}

llvm::MemoryBuffer * prepareSourceFile( clang::FileManager & fileManager, clang::FileEntry const & fileEntry )
{
    llvm::MemoryBuffer * memoryBuffer( fileManager.getBufferForFile( &fileEntry, 0, true ) );
    convertEncodingIfNeeded( memoryBuffer );
    return memoryBuffer;
}
